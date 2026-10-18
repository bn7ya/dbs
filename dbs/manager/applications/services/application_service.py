from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone
from rest_framework.exceptions import ErrorDetail, NotFound, ValidationError

from dbs.manager.accounts.services import AccountService
from dbs.manager.activity.services import ActivityService
from dbs.manager.applications.models import Application
from dbs.manager.applications.paths import host_path
from dbs.manager.applications.repositories import ApplicationRepository
from dbs.manager.common.exceptions import error_code_of
from dbs.manager.common.paths import absolute_path
from dbs.manager.redeploy import catalogue
from dbs.manager.servers import versions
from dbs.manager.servers.exceptions import (
    HostKeyChanged,
    RemoteCommandFailed,
    SSHAuthFailed,
    SSHUnreachable,
)
from dbs.manager.servers.gateways import ContainerTarget, DbsProfile, RemoteHost
from dbs.manager.servers.services import pythons, vault_contexts
from dbs.manager.servers.services.connection_service import ServerConnectionService
from dbs.manager.servers.services.server_service import (
    ServerService,
    changed_fields,
    last_line,
    output_of,
    require_account_password,
)
from dbs.manager.vault import seal_text
from dbs.manager.permissions import Capability, requires

if TYPE_CHECKING:
    from django.contrib.auth.models import AnonymousUser, User

PLAIN_FIELDS = (
    "name",
    "kind",
    "engine",
    "compose_project",
    "compose_service",
    "container_name",
    "python_path",
    "manage_path",
    "settings_module",
    "env_location",
)
LIST_FIELDS = ("compose_files", "mounts")
OPTIONAL_PATH_FIELDS = ("project_dir", "workdir", "env_path")
REQUIRED_PATH_FIELDS = ("remote_backup_dir",)
UNGUARDED_FIELDS = frozenset({"name"})
SETUP_FIELDS = frozenset(
    {
        "kind",
        "engine",
        "compose_project",
        "compose_service",
        "compose_files",
        "container_name",
        "project_dir",
        "workdir",
        "python_path",
        "manage_path",
        "settings_module",
        "remote_backup_dir",
        "mounts",
        "file_roots",
        "env_path",
        "env_location",
    }
)
SETUP_WINDOW = timedelta(hours=1)
HEALTH_STATUSES = ("ok", "warn", "error")
CONNECTION_ERRORS = (HostKeyChanged, SSHAuthFailed, SSHUnreachable)
REPORTED_OUTPUT_LIMIT = 200
IS_FOLDER = "import os, sys; sys.exit(0 if os.path.isdir(sys.argv[1]) else 1)"
IS_FILE = "import os, sys; sys.exit(0 if os.path.isfile(sys.argv[1]) else 1)"

ABSOLUTE_PATH_REQUIRED = (
    "Use an absolute path that starts with / and has no '..' in it."
)
NAME_TAKEN = "Another application already has this name."
COMPOSE_SERVICE_REQUIRED = "Name the Compose service that runs the application."
COMPOSE_FOLDER_REQUIRED = "Enter the folder that holds the compose file."
CONTAINER_REQUIRED = "Name the container that runs the application."
ENGINE_REQUIRED = "Choose Docker or Podman."
ACCOUNT_PASSWORD_REQUIRED = "Enter your own password to change this."
DELETE_PASSWORD_REQUIRED = "Enter your own password to remove an application."
DEPLOY_STEPS_PASSWORD_REQUIRED = "Enter your own password to change the deploy steps."

Errors = dict[str, list[ErrorDetail]]


class Action:
    CREATE = "application.create"
    UPDATE = "application.update"
    DELETE = "application.delete"
    CHECK = "application.check"
    PASSPHRASE_REVEAL = "application.passphrase_reveal"
    PASSPHRASE_CAPTURE = "application.passphrase_capture"
    DEPLOY_STEPS = "application.deploy_steps"


def _add(errors: Errors, field: str, message: str, code: str) -> None:
    errors.setdefault(field, []).append(ErrorDetail(message, code=code))


@dataclass(frozen=True)
class CheckedApplication:
    application: Application
    compatibility: dict[str, Any]


class ApplicationService:
    def __init__(self, user: User | AnonymousUser | None) -> None:
        self.user: User | AnonymousUser | None = user
        self.applications = ApplicationRepository()
        self.servers = ServerService(user)
        self.connections = ServerConnectionService(user)
        self.activity = ActivityService(user)

    def list(
        self, search: str | None = None, server: UUID | None = None
    ) -> QuerySet[Application]:
        return self.applications.search((search or "").strip() or None, server)

    def with_env_path(self) -> QuerySet[Application]:
        return self.applications.with_env_path()

    def get(self, application_id: UUID) -> Application:
        application = self.applications.find(application_id)
        if application is None:
            raise NotFound()
        return application

    @requires(Capability.APPLICATIONS_MANAGE)
    def create(self, *, server: UUID, **data: Any) -> Application:
        host = self.servers.get(server)
        errors: Errors = {}
        fields = {name: data[name] for name in PLAIN_FIELDS if name in data}
        fields |= {name: list(data[name]) for name in LIST_FIELDS if name in data}
        fields |= self._paths(data, errors)
        self._runtime(fields, errors, current=None)
        if self.applications.name_in_use(data["name"]):
            _add(errors, "name", NAME_TAKEN, "name_taken")
        if errors:
            raise ValidationError(errors)
        fields["backup_passphrase_sealed"] = seal_text(
            data.get("backup_passphrase") or secrets.token_urlsafe(32),
            context=vault_contexts.BACKUP_PASSPHRASE,
        )
        if data.get("discovered"):
            fields["discovered_at"] = timezone.now()
        with transaction.atomic():
            application = self._saved(
                lambda: self.applications.create(
                    created_by=cast("User | None", self.user), server=host, **fields
                )
            )
            self.activity.record(
                Action.CREATE, subject=application, target=application.name
            )
        return application

    @requires(Capability.APPLICATIONS_MANAGE)
    def update(
        self, application_id: UUID, account_password: str = "", **data: Any
    ) -> Application:
        application = self.get(application_id)
        errors: Errors = {}
        changes = {name: data[name] for name in PLAIN_FIELDS if name in data}
        changes |= {name: list(data[name]) for name in LIST_FIELDS if name in data}
        changes |= self._paths(data, errors)
        self._runtime(changes, errors, current=application)
        if "name" in data and self.applications.name_in_use(
            data["name"], excluding=application.pk
        ):
            _add(errors, "name", NAME_TAKEN, "name_taken")
        if errors:
            raise ValidationError(errors)
        if data.get("backup_passphrase"):
            changes["backup_passphrase_sealed"] = seal_text(
                data["backup_passphrase"], context=vault_contexts.BACKUP_PASSPHRASE
            )
        if data.get("discovered"):
            changes["discovered_at"] = timezone.now()
        changed = changed_fields(application, changes)
        free = (
            UNGUARDED_FIELDS | SETUP_FIELDS | {"discovered_at"}
            if self.in_setup(application)
            else UNGUARDED_FIELDS
        )
        guarded = not free.issuperset(changed)
        if guarded:
            require_account_password(account_password, ACCOUNT_PASSWORD_REQUIRED)
        name = changes.get("name", application.name)
        with self.activity.track(
            Action.UPDATE, subject=application, target=name
        ) as entry:
            entry.detail = {"fields": changed}
            if guarded or account_password:
                AccountService(self.user).confirm_password(account_password)
            return self._saved(lambda: self.applications.update(application, **changes))

    def require_step_up(self, application: Application, account_password: str) -> None:
        if not account_password and not self.in_setup(application):
            require_account_password("", ACCOUNT_PASSWORD_REQUIRED)

    def confirm_step_up(self, account_password: str) -> None:
        if account_password:
            AccountService(self.user).confirm_password(account_password)

    def in_setup(self, application: Application) -> bool:
        return (
            self.user is not None
            and self.user.is_authenticated
            and application.created_by_id == self.user.pk
            and application.created_at > timezone.now() - SETUP_WINDOW
            and application.last_check_status != Application.CheckStatus.OK
        )

    @requires(Capability.APPLICATIONS_MANAGE)
    def delete(self, application_id: UUID, account_password: str = "") -> None:
        application = self.get(application_id)
        require_account_password(account_password, DELETE_PASSWORD_REQUIRED)
        with self.activity.track(
            Action.DELETE, subject=application, target=application.name
        ):
            AccountService(self.user).confirm_password(account_password)
            self.applications.soft_delete(application)

    @requires(Capability.APPLICATIONS_MANAGE)
    def set_deploy_steps(
        self, application_id: UUID, steps: Any, account_password: str = ""
    ) -> Application:
        application = self.get(application_id)
        cleaned = catalogue.validated(steps, application)
        require_account_password(account_password, DEPLOY_STEPS_PASSWORD_REQUIRED)
        with self.activity.track(
            Action.DEPLOY_STEPS, subject=application, target=application.name
        ) as entry:
            entry.detail = {"steps": [step["kind"] for step in cleaned]}
            AccountService(self.user).confirm_password(account_password)
            return self.applications.update(application, deploy_steps=cleaned)

    @requires(Capability.APPLICATIONS_PASSPHRASE)
    def reveal_passphrase(self, application_id: UUID, password: str) -> str:
        application = self.get(application_id)
        with self.activity.track(
            Action.PASSPHRASE_REVEAL, subject=application, target=application.name
        ):
            AccountService(self.user).confirm_password(password)
            return self.connections.backup_passphrase(application)

    @requires(Capability.APPLICATIONS_CHECK)
    def check(self, application_id: UUID) -> Application:
        application = self.get(application_id)
        with self.activity.track(
            Action.CHECK, subject=application, target=application.name
        ) as entry:
            try:
                with self.connections.open(application) as remote:
                    report = self._inspect(application, remote)
                    health = self._health(application, remote, report["dbs_version"])
                    report["panel_schedule"] = _panel_schedule(health)
                    limits = self._limits(application, remote, report)
            except CONNECTION_ERRORS as exc:
                self._record(
                    application,
                    Application.CheckStatus.FAILED,
                    error_code_of(exc),
                    {},
                )
                entry.detail = {"status": Application.CheckStatus.FAILED}
                raise
            status = (
                Application.CheckStatus.OK
                if _ready(report)
                else Application.CheckStatus.PROBLEM
            )
            entry.detail = {"status": status}
            self.applications.update(application, last_health=health, **limits)
            return self._record(application, status, "", report)

    def checked(self, application_id: UUID) -> CheckedApplication:
        application = self.check(application_id)
        return CheckedApplication(
            application=application, compatibility=self.compatibility(application)
        )

    def compatibility(self, application: Application) -> dict[str, Any]:
        remote = (application.last_check_report or {}).get("dbs_version")
        return versions.compatibility(remote)

    @requires(Capability.APPLICATIONS_MANAGE)
    def capture_passphrase(self, application_id: UUID) -> Application:
        application = self.get(application_id)
        with self.activity.track(
            Action.PASSPHRASE_CAPTURE, subject=application, target=application.name
        ):
            with self.connections.open(application) as remote:
                result = remote.run_manage(
                    self.connections.dbs_profile(application), ["dbs_key", "--show"]
                )
            lines = result.stdout.strip().splitlines()
            if not result.ok or not lines or not lines[-1].strip():
                raise RemoteCommandFailed(output=result.stderr.strip()[-500:])
            sealed = seal_text(
                lines[-1].strip(), context=vault_contexts.BACKUP_PASSPHRASE
            )
            return self.applications.update(application, backup_passphrase_sealed=sealed)

    def _health(
        self, application: Application, remote: RemoteHost, remote_version: str | None
    ) -> dict[str, Any] | None:
        if remote_version is None:
            return None
        try:
            result = remote.run_manage(
                self.connections.dbs_profile(application), ["dbs", "health", "--json"]
            )
        except RemoteCommandFailed:
            return None
        return _health_report(result.stdout)

    def _limits(
        self, application: Application, remote: RemoteHost, report: dict[str, Any]
    ) -> dict[str, bool | None]:
        running = (report.get("container") or {}).get("running", False)
        return {
            "timeout_in_container": (
                remote.has_timeout(self.connections.dbs_profile(application))
                if running
                else None
            ),
        }

    def _inspect(self, application: Application, remote: RemoteHost) -> dict[str, Any]:
        profile = self.connections.dbs_profile(application)
        project_dir = application.project_dir or None
        container = _container_report(remote, profile) if profile.container else None
        probe = pythons.probe(remote, profile)
        dbs_version = probe.version
        backup_command = None
        if project_dir or profile.container is not None:
            backup_command = _succeeds(remote, profile, ["dbs_backup", "--help"])
        report = {
            "system": output_of(remote, ["uname", "-sr"]),
            "dbs_version": dbs_version,
            "dbs_error": probe.error,
            "python_suggestion": (
                None
                if dbs_version is not None or project_dir is None
                else _python_suggestion(application, remote, profile)
            ),
            "backup_command": backup_command,
            "env_file": (
                _present(application, remote, profile, application.env_path, IS_FILE)
                if application.env_path
                else None
            ),
            "roots": {
                root: _present(application, remote, profile, root, IS_FOLDER)
                for root in application.file_roots
            },
            "remote_backup_dir": _present(
                application, remote, profile, application.remote_backup_dir, IS_FOLDER
            ),
        }
        if container is not None:
            report["container"] = container
        return report

    def _record(
        self, application: Application, status: str, error: str, report: dict[str, Any]
    ) -> Application:
        return self.applications.update(
            application,
            last_check_status=status,
            last_check_error=error,
            last_check_report=report,
            last_checked_at=timezone.now(),
        )

    def _paths(self, data: dict[str, Any], errors: Errors) -> dict[str, Any]:
        cleaned: dict[str, Any] = {}
        for name in (*OPTIONAL_PATH_FIELDS, *REQUIRED_PATH_FIELDS):
            if name not in data:
                continue
            if name in OPTIONAL_PATH_FIELDS and not data[name]:
                cleaned[name] = ""
                continue
            path = absolute_path(data[name])
            if path is not None:
                cleaned[name] = path
            else:
                _add(errors, name, ABSOLUTE_PATH_REQUIRED, "absolute_path_required")
        if "file_roots" in data:
            roots = [absolute_path(root) for root in data["file_roots"]]
            if None in roots:
                _add(
                    errors,
                    "file_roots",
                    ABSOLUTE_PATH_REQUIRED,
                    "absolute_path_required",
                )
            else:
                cleaned["file_roots"] = list(dict.fromkeys(roots))
        return cleaned

    def _runtime(
        self, changes: dict[str, Any], errors: Errors, *, current: Application | None
    ) -> None:
        def value(name: str, default: Any) -> Any:
            if name in changes:
                return changes[name]
            return getattr(current, name) if current is not None else default

        kind = value("kind", Application.Kind.HOST)
        if kind == Application.Kind.HOST:
            if "kind" in changes:
                changes["engine"] = Application.Engine.NONE
            return
        if not value("engine", ""):
            _add(errors, "engine", ENGINE_REQUIRED, "engine_required")
        if kind == Application.Kind.COMPOSE:
            if not value("compose_service", ""):
                _add(
                    errors,
                    "compose_service",
                    COMPOSE_SERVICE_REQUIRED,
                    "compose_service_required",
                )
            if not value("project_dir", ""):
                _add(
                    errors,
                    "project_dir",
                    COMPOSE_FOLDER_REQUIRED,
                    "compose_folder_required",
                )
        elif not value("container_name", ""):
            _add(errors, "container_name", CONTAINER_REQUIRED, "container_required")

    def _saved(self, write: Callable[[], Application]) -> Application:
        try:
            with transaction.atomic():
                return write()
        except IntegrityError as exc:
            raise ValidationError(
                {"name": [ErrorDetail(NAME_TAKEN, code="name_taken")]}
            ) from exc


def _present(
    application: Application,
    remote: RemoteHost,
    profile: DbsProfile,
    path: str,
    probe: str,
) -> bool:
    if not application.in_container:
        return _exists(remote, path)
    if path == application.env_path and not application.env_in_container:
        return _exists(remote, path)
    on_host = host_path(application, path)
    if on_host is not None:
        return _exists(remote, on_host)
    try:
        return bool(
            remote.run_python(profile, ["-c", probe, path], with_settings=False).ok
        )
    except RemoteCommandFailed:
        return False


def _python_suggestion(
    application: Application, remote: RemoteHost, profile: DbsProfile
) -> dict[str, str] | None:
    found_here = (
        pythons.container_pythons(application.workdir)
        if profile.container
        else pythons.candidates(remote, application.project_dir)
    )
    others = [python for python in found_here if python != application.python_path]
    found = pythons.with_dbs(remote, others, profile)
    if found is None:
        return None
    return {"python_path": found.python_path, "dbs_version": found.dbs_version}


def _succeeds(remote: RemoteHost, profile: DbsProfile, arguments: list[str]) -> bool:
    try:
        ok: bool = remote.run_manage(profile, arguments).ok
        return ok
    except RemoteCommandFailed:
        return False


def _container_report(remote: RemoteHost, profile: DbsProfile) -> dict[str, Any]:
    target = cast(ContainerTarget, profile.container)
    try:
        version = remote.run(target.version_argv())
    except RemoteCommandFailed:
        return {"engine": target.engine, "version": None, "error": "", "running": False}
    if not version.ok:
        return {
            "engine": target.engine,
            "version": None,
            "error": last_line(version),
            "running": False,
        }
    reported = version.stdout.strip()[:REPORTED_OUTPUT_LIMIT]
    try:
        listed = remote.run_engine(profile, target.running_argv())
    except RemoteCommandFailed:
        return {"engine": target.engine, "version": reported, "error": "", "running": False}
    return {
        "engine": target.engine,
        "version": reported,
        "error": "" if listed.ok else last_line(listed),
        "running": listed.ok and target.running_in(listed.stdout),
    }


def _exists(remote: RemoteHost, path: str) -> bool:
    try:
        return remote.exists(path)
    except RemoteCommandFailed:
        return False


def _ready(report: dict[str, Any]) -> bool:
    container = report.get("container")
    return (
        (
            container is None
            or (container["version"] is not None and container["running"])
        )
        and report["dbs_version"] is not None
        and report["backup_command"] is not False
        and report["env_file"] is not False
        and all(report["roots"].values())
        and bool(report["remote_backup_dir"])
    )


def _health_report(stdout: str) -> dict[str, Any] | None:
    try:
        report = json.loads(stdout.strip() or "null")
    except ValueError:
        return None
    if not isinstance(report, dict) or report.get("status") not in HEALTH_STATUSES:
        return None
    return report


def _panel_schedule(health: dict[str, Any] | None) -> dict[str, Any] | None:
    schedule = (health or {}).get("schedule")
    if not isinstance(schedule, dict):
        return None
    return {
        "enabled": bool(schedule.get("enabled")),
        "mode": str(schedule.get("mode") or ""),
    }
