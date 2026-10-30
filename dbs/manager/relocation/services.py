from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any
from uuid import UUID

from django.db import transaction
from django.views.decorators.debug import sensitive_variables
from rest_framework.exceptions import APIException, ErrorDetail, ValidationError

from dbs import audit
from dbs.manager.accounts.exceptions import InvalidPassword, TooManyAttempts
from dbs.manager.accounts.services import AccountService
from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.activity.services import ActivityService
from dbs.manager.applications.models import Application
from dbs.manager.applications.services import ApplicationService
from dbs.manager.common.exceptions import error_code_of
from dbs.manager.common.paths import absolute_path
from dbs.manager.permissions import Capability, requires
from dbs.manager.redeploy.exceptions import ConfirmNameMismatch
from dbs.manager.relocation.exceptions import (
    MoveNotResumable,
    NothingToMove,
    SameServer,
    ServerMoveRunning,
)
from dbs.manager.relocation.locks import ServerMoveLock
from dbs.manager.relocation.privileged import SudoPasswords
from dbs.manager.relocation.steps import (
    ACTION,
    SUCCEEDED,
    Move,
    plan_phase,
    step_key,
)
from dbs.manager.runner import get_runner
from dbs.manager.servers.exceptions import failure_facts
from dbs.manager.servers.models import Server
from dbs.manager.servers.services import ServerService
from dbs.models import AuditEvent

PASSWORD_REQUIRED = "Enter your own password to move for real."
NOT_ON_SOURCE = "Choose an application that runs on the server being moved."
ABSOLUTE_PATH_REQUIRED = "Use an absolute path that starts with / and has no '..' in it."

Detail = dict[str, Any]


def _field(field: str, message: str, code: str) -> ValidationError:
    return ValidationError({field: [ErrorDetail(message, code=code)]})


class RelocationService:
    def __init__(self, user: Any = None) -> None:
        self.user = user
        self.servers = ServerService(user)
        self.applications = ApplicationService(user)
        self.activity = ActivityService(user)
        self.locks = ServerMoveLock()

    @sensitive_variables("password", "sudo_password", "source_sudo_password")
    @requires(Capability.RELOCATION_RUN)
    def start(
        self,
        *,
        source_server: UUID,
        target_server: UUID,
        applications: Iterable[Mapping[str, Any]] = (),
        rehearsal: bool = True,
        password: str = "",
        confirm_name: str = "",
        sudo_password: str = "",
        source_sudo_password: str = "",
        resume_of: int | None = None,
    ) -> AuditEvent:
        source = self.servers.get(source_server)
        target = self.servers.get(target_server)
        if source.pk == target.pk:
            raise SameServer()
        detail: Detail = {
            "source_server": str(source.pk),
            "target_server": str(target.pk),
            "rehearsal": rehearsal,
            "resume_of": resume_of,
            "phases": [plan_phase()],
            "inventory": None,
            "leftovers": [],
            "created_applications": [],
        }
        if resume_of is not None:
            earlier = self._resumable(resume_of, source, target)
            detail["choices"] = earlier.data["choices"]
            detail["previous_phases"] = earlier.data.get("phases", [])
            detail["done_before"] = [
                list(step_key(phase, step))
                for phase in earlier.data.get("phases", [])
                if phase["phase"] != "plan"
                for step in phase["steps"]
                if step["status"] == SUCCEEDED or step.get("reason") == "done_before"
            ]
            detail["created_applications"] = earlier.data.get("created_applications", [])
        else:
            detail["choices"] = self._choices(source, applications)
        if not detail["choices"]:
            raise NothingToMove()
        if not rehearsal:
            self._confirm(target, detail, password, confirm_name)
        return self._queue(source, target, detail, SudoPasswords(sudo_password, source_sudo_password))

    def _choices(
        self, source: Server, applications: Iterable[Mapping[str, Any]]
    ) -> list[Detail]:
        given = {str(choice["application"]): choice for choice in applications}
        on_source = list(self.applications.list(server=source.pk))
        chosen = [app for app in on_source if not given or str(app.pk) in given]
        unknown = set(given) - {str(app.pk) for app in on_source}
        if unknown:
            raise _field("applications", NOT_ON_SOURCE, "not_on_source")
        choices = []
        for application in chosen:
            choice = given.get(str(application.pk), {})
            folder = choice.get("folder") or application.project_dir
            if folder and absolute_path(folder) is None:
                raise _field("applications", ABSOLUTE_PATH_REQUIRED, "absolute_path_required")
            choices.append(
                {
                    "application": str(application.pk),
                    "name": (choice.get("name") or application.name).strip(),
                    "folder": absolute_path(folder) if folder else "",
                    "skip_volumes": sorted(set(choice.get("skip_volumes") or [])),
                    "copy_plans": bool(choice.get("copy_plans", True)),
                }
            )
        return choices

    def _resumable(self, activity_id: int, source: Server, target: Server) -> AuditEvent:
        earlier = ActivityRepository().find_joined(activity_id)
        data = (earlier.data if earlier is not None else None) or {}
        if (
            earlier is None
            or earlier.action != ACTION
            or earlier.status != audit.FAILED
            or data.get("rehearsal", True)
            or data.get("source_server") != str(source.pk)
            or data.get("target_server") != str(target.pk)
            or not data.get("choices")
        ):
            raise MoveNotResumable()
        return earlier

    @sensitive_variables("password")
    def _confirm(self, target: Server, detail: Detail, password: str, confirm_name: str) -> None:
        if not password:
            raise _field("password", PASSWORD_REQUIRED, "required")
        if confirm_name.strip() != target.name:
            raise ConfirmNameMismatch()
        try:
            AccountService(self.user).confirm_password(password)
        except (InvalidPassword, TooManyAttempts) as exc:
            self.activity.record(
                ACTION,
                subject=target,
                target=target.name,
                detail={key: detail[key] for key in ("source_server", "target_server", "rehearsal")},
                status=audit.FAILED,
                error_code=error_code_of(exc),
            )
            raise

    @sensitive_variables("passwords")
    def _queue(
        self, source: Server, target: Server, detail: Detail, passwords: SudoPasswords
    ) -> AuditEvent:
        servers = (source.pk, target.pk)
        with transaction.atomic():
            job = self.activity.queue(
                ACTION, subject=target, target=f"{source.name} → {target.name}", detail=detail
            )
            if not self.locks.acquire(servers, job.pk):
                raise ServerMoveRunning()

            def send() -> None:
                try:
                    get_runner().submit(RelocationService().run, job.pk, passwords)
                except Exception as exc:
                    self.activity.fail(job.pk, exc)
                    self.locks.release(servers, job.pk)
                    raise

            transaction.on_commit(send)
        return job

    @sensitive_variables("passwords")
    def run(self, activity_id: int, passwords: SudoPasswords) -> None:
        jobs = ActivityService(None)
        job = jobs.start(activity_id)
        if job is None:
            self._let_go(activity_id)
            return
        detail = dict(job.data)
        servers = (UUID(detail["source_server"]), UUID(detail["target_server"]))
        try:
            Move(job, detail, passwords).run()
        except APIException as exc:
            jobs.fail(job.pk, exc, detail={**detail, **failure_facts(exc)})
        except BaseException as exc:
            jobs.fail(job.pk, exc, detail=detail)
            raise
        else:
            jobs.succeed(job.pk, detail)
        finally:
            self.locks.release(servers, job.pk)

    def _let_go(self, activity_id: int) -> None:
        entry = ActivityRepository().find_joined(activity_id)
        data = (entry.data if entry is not None else None) or {}
        servers = [data.get("source_server"), data.get("target_server")]
        self.locks.release([UUID(server) for server in servers if server], activity_id)

    def moving(self, server: Server | Application) -> bool:
        server_id = server.server_id if isinstance(server, Application) else server.pk
        return self.locks.held(server_id)
