from __future__ import annotations

from collections.abc import Callable
from typing import Any, Optional
from uuid import UUID

from django.conf import settings
from rest_framework.exceptions import APIException, ErrorDetail, ValidationError

from dbs import audit, validate_backup
from dbs.manager.accounts.exceptions import InvalidPassword, TooManyAttempts
from dbs.manager.accounts.services import AccountService
from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.activity.services import ActivityService
from dbs.manager.backups.exceptions import BackupMissing
from dbs.manager.backups.locks import TakeLock
from dbs.manager.backups.models import BackupFile
from dbs.manager.backups.repositories import BackupFileRepository
from dbs.manager.backups.services.backup_run_service import BackupRunService
from dbs.manager.backups.services.job_queue import JobQueue
from dbs.manager.backups.storage import BackupStorage
from dbs.manager.common.exceptions import error_code_of
from dbs.manager.envfiles.exceptions import EnvPathMissing
from dbs.manager.envfiles.repositories import EnvVersionRepository
from dbs.manager.envfiles.services import EnvFileService
from dbs.manager.redeploy.exceptions import (
    ConfirmNameMismatch,
    NoBackupToRehearse,
    NotRevertable,
    SameServer,
    SourceUnreachable,
    TargetNotReady,
)
from dbs.manager.runner import get_runner
from dbs.manager.servers.exceptions import (
    HostKeyChanged,
    PassphraseMissing,
    RemoteCommandFailed,
    RemoteNotFound,
    RestoreFailed,
    SSHAuthFailed,
    SSHUnreachable,
)
from dbs.manager.servers.models import Server
from dbs.manager.servers.services import ServerConnectionService, ServerService
from dbs.models import AuditEvent

RUN = "redeploy.run"
REVERT = "redeploy.revert"
MOVE_STEPS = (
    "check",
    "source_backup",
    "record_env",
    "safety_backup",
    "env",
    "migrate",
    "restore",
    "final_check",
)
MOVE_REHEARSAL_STEPS = ("check", "source_backup", "safety_backup", "restore")
CHANGING_STEPS = ("env", "migrate", "restore", "final_check")
REVERT_STEPS = ("check", "env", "restore")
REVERT_REHEARSAL_STEPS = ("check", "restore")
PENDING = "pending"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
SKIPPED = "skipped"
UNREACHABLE = (HostKeyChanged, SSHAuthFailed, SSHUnreachable)
NO_OP = ["true"]
NOT_FOUND = "Choose one of the source server's own files."
PASSWORD_REQUIRED = "Enter your own password to redeploy for real."

Detail = dict[str, Any]
Step = Callable[[Detail, Server, AuditEvent], Optional[Detail]]


def _not_found(field: str) -> ValidationError:
    return ValidationError({field: [ErrorDetail(NOT_FOUND, code="not_found")]})


class RedeployService:
    def __init__(self, user: Any = None) -> None:
        self.user = user
        self.servers = ServerService(user)
        self.files = BackupFileRepository()
        self.versions = EnvVersionRepository()
        self.activity = ActivityService(user)

    def start(
        self,
        *,
        source_server: UUID,
        target_server: UUID,
        backup: UUID | None = None,
        env_version: UUID | None = None,
        flush: bool = False,
        rehearsal: bool = True,
        password: str = "",
        confirm_name: str = "",
    ) -> AuditEvent:
        source = self.servers.get(source_server)
        target = self.servers.get(target_server)
        if source.pk == target.pk:
            raise SameServer()
        chosen = self._chosen_backup(backup, source)
        if env_version is not None:
            self._source_version(env_version, source)
            if not target.env_path:
                raise EnvPathMissing()
        if not source.has_backup_passphrase:
            raise PassphraseMissing()
        detail: Detail = {
            "source_server": str(source.pk),
            "target_server": str(target.pk),
            "backup": chosen,
            "env_version": None if env_version is None else str(env_version),
            "flush": flush,
            "rehearsal": rehearsal,
        }
        runs = MOVE_REHEARSAL_STEPS if rehearsal else MOVE_STEPS
        detail["steps"] = _planned(
            MOVE_STEPS,
            [step for step in runs if step != "env" or env_version is not None],
        )
        if not rehearsal:
            self._confirm(RUN, target, detail, password, confirm_name)
        return self._queue(RUN, target, detail)

    def revert(
        self,
        move_id: int,
        *,
        rehearsal: bool = True,
        password: str = "",
        confirm_name: str = "",
    ) -> AuditEvent:
        move = self.activity.get(move_id)
        if not _revertable(move):
            raise NotRevertable()
        target = self.servers.get(UUID(move.subject))
        detail: Detail = {
            "move": move.pk,
            "target_server": str(target.pk),
            "env_version": move.data.get("target_env_version"),
            "backup": move.data.get("safety_backup"),
            "rehearsal": rehearsal,
        }
        runs = REVERT_REHEARSAL_STEPS if rehearsal else REVERT_STEPS
        detail["steps"] = _planned(
            REVERT_STEPS, [step for step in runs if _has_material(step, detail)]
        )
        if not rehearsal:
            self._confirm(REVERT, target, detail, password, confirm_name)
        return self._queue(REVERT, target, detail)

    def run(self, activity_id: int) -> None:
        jobs = ActivityService(None)
        job = jobs.start(activity_id)
        if job is None:
            self._let_go(activity_id)
            return
        target_id = UUID(job.subject)
        locks = TakeLock()
        detail = dict(job.data)
        try:
            if not locks.hold(target_id, job.pk):
                raise locks.refusal(target_id)
            self._steps(job, detail, target_id)
        except APIException as exc:
            jobs.fail(job.pk, exc, detail=_failed_detail(detail, exc))
        except BaseException as exc:
            jobs.fail(job.pk, exc, detail=detail)
            raise
        else:
            jobs.succeed(job.pk, detail)
        finally:
            locks.release(target_id, job.pk)

    def _steps(self, job: AuditEvent, detail: Detail, target_id: UUID) -> None:
        actor = job.actor
        jobs = ActivityService(None)
        work = self._work(job.action)
        prefix = "redeploy." if job.action == RUN else f"{REVERT}_"
        for step in detail["steps"]:
            if step["status"] == SKIPPED:
                continue
            step["status"] = RUNNING
            jobs.progress(job.pk, detail)
            target = ServerService(actor).get(target_id)
            try:
                with ActivityService(actor).track(
                    f"{prefix}{step['step']}", server=target, target=target.name
                ) as entry:
                    outcome = work[step["step"]](detail, target, job)
                    entry.detail = outcome or {}
            except BaseException:
                step["status"] = FAILED
                detail["failed_step"] = step["step"]
                for later in detail["steps"]:
                    if later["status"] == PENDING:
                        later["status"] = SKIPPED
                if job.action == RUN:
                    detail["revertable"] = _may_revert(detail, step["step"])
                raise
            step["status"] = SKIPPED if outcome is None else SUCCEEDED
            jobs.progress(job.pk, detail)

    def _work(self, action: str) -> dict[str, Step]:
        if action == REVERT:
            return {
                "check": self._check,
                "env": self._push_recorded_env,
                "restore": self._restore_safety_backup,
            }
        return {
            "check": self._check,
            "source_backup": self._source_backup,
            "record_env": self._record_env,
            "safety_backup": self._safety_backup,
            "env": self._push_env,
            "migrate": self._migrate,
            "restore": self._restore,
            "final_check": self._check,
        }

    def _check(self, detail: Detail, target: Server, job: AuditEvent) -> Detail:
        checked = ServerService(job.actor).check(target.pk)
        report = checked.last_check_report or {}
        if (
            report.get("dbs_version") is None
            or report.get("backup_command") is not True
        ):
            raise TargetNotReady()
        return {"status": checked.last_check_status}

    def _source_backup(
        self, detail: Detail, target: Server, job: AuditEvent
    ) -> Detail:
        source = ServerService(job.actor).get(UUID(detail["source_server"]))
        if detail["rehearsal"]:
            reachable = self._answers(source, job.actor)
            detail["source_reachable"] = reachable
            if detail["backup"] is None:
                raise NoBackupToRehearse()
            return {"reachable": reachable, "backup": detail["backup"]}
        try:
            file = self._fresh_backup(source, job)
        except UNREACHABLE as exc:
            if detail["backup"] is None:
                raise SourceUnreachable() from exc
            detail.update(
                used_backup=detail["backup"],
                fresh_backup=False,
                source_error=error_code_of(exc),
            )
            return {"backup": detail["backup"], "fresh": False}
        detail.update(used_backup=str(file.pk), fresh_backup=True)
        return {"backup": str(file.pk), "fresh": True}

    def _record_env(
        self, detail: Detail, target: Server, job: AuditEvent
    ) -> Detail | None:
        if not target.env_path:
            return None
        try:
            pulled = EnvFileService(job.actor).pull(target.pk)
        except RemoteNotFound:
            return {"recorded": False}
        detail["target_env_version"] = str(pulled.version.pk)
        return {"version": str(pulled.version.pk)}

    def _safety_backup(
        self, detail: Detail, target: Server, job: AuditEvent
    ) -> Detail | None:
        holds_data = self._migrated(target, job.actor)
        detail["target_had_data"] = holds_data
        if not holds_data:
            return None
        if detail["rehearsal"]:
            return {"would_back_up": True}
        file = BackupRunService().back_up(job, target, keep_remote=0)
        detail["safety_backup"] = str(file.pk)
        return {"backup": str(file.pk)}

    def _push_env(self, detail: Detail, target: Server, job: AuditEvent) -> Detail:
        version = EnvFileService(job.actor).copy_to(UUID(detail["env_version"]), target)
        return {"version": str(version.pk)}

    def _migrate(self, detail: Detail, target: Server, job: AuditEvent) -> Detail:
        result = self._manage(target, job.actor, "migrate", "--noinput")
        if not result.ok:
            raise RemoteCommandFailed(
                output=f"{result.stdout}\n{result.stderr}".strip()[-500:]
            )
        return {}

    def _restore(self, detail: Detail, target: Server, job: AuditEvent) -> Detail:
        file = self._stored(detail.get("used_backup") or detail["backup"])
        if detail["rehearsal"] and not detail.get("target_had_data"):
            return self._validate(file, job.actor)
        return self._restore_file(
            file,
            target,
            job.actor,
            flush=detail["flush"],
            dry_run=detail["rehearsal"],
        )

    def _push_recorded_env(
        self, detail: Detail, target: Server, job: AuditEvent
    ) -> Detail:
        return self._push_env(detail, target, job)

    def _restore_safety_backup(
        self, detail: Detail, target: Server, job: AuditEvent
    ) -> Detail:
        file = self._stored(detail["backup"])
        return self._restore_file(
            file, target, job.actor, flush=True, dry_run=detail["rehearsal"]
        )

    def _fresh_backup(self, source: Server, job: AuditEvent) -> BackupFile:
        locks = TakeLock()
        if not locks.hold(source.pk, job.pk):
            raise locks.refusal(source.pk)
        try:
            return BackupRunService().back_up(job, source, keep_remote=0)
        finally:
            locks.release(source.pk, job.pk)

    def _answers(self, server: Server, actor: Any) -> bool:
        try:
            with ServerConnectionService(actor).open(server) as remote:
                remote.run(NO_OP)
        except UNREACHABLE:
            return False
        return True

    def _manage(self, target: Server, actor: Any, *arguments: str) -> Any:
        connections = ServerConnectionService(actor)
        with connections.open(target) as remote:
            return remote.run_manage(
                connections.dbs_profile(target),
                arguments,
                timeout=settings.BACKUP_EXEC_TIMEOUT,
            )

    def _migrated(self, target: Server, actor: Any) -> bool:
        return bool(self._manage(target, actor, "migrate", "--check", "--noinput").ok)

    def _stored(self, file_id: str) -> BackupFile:
        file = self.files.find_including_deleted(UUID(file_id))
        if file is None or file.removed_at is not None:
            raise BackupMissing()
        return file

    def _validate(self, file: BackupFile, actor: Any) -> Detail:
        passphrase = ServerConnectionService(actor).backup_passphrase(file.server)
        try:
            with BackupStorage().open_read(file.storage_path) as handle:
                data = handle.read()
        except FileNotFoundError as exc:
            raise BackupMissing() from exc
        result = validate_backup(data, passphrase)
        if not (result.ok and result.decrypted_ok):
            raise RestoreFailed()
        return {"validated": True, "target_not_migrated": True}

    def _restore_file(
        self,
        file: BackupFile,
        target: Server,
        actor: Any,
        *,
        flush: bool,
        dry_run: bool,
    ) -> Detail:
        connections = ServerConnectionService(actor)
        try:
            handle = BackupStorage().open_read(file.storage_path)
        except FileNotFoundError as exc:
            raise BackupMissing() from exc
        with handle, connections.open(target) as remote:
            report = remote.restore_dbs_backup(
                handle,
                profile=connections.dbs_profile(target),
                passphrase=connections.backup_passphrase(file.server),
                remote_dir=target.remote_backup_dir,
                flush=flush,
                dry_run=dry_run,
            )
        outcome: Detail = {
            "backup": str(file.pk),
            "records": report.records,
            "files": report.files,
            "flushed": report.flushed,
            "healed": report.healed,
        }
        if report.copy_left:
            outcome["copy_left"] = report.copy_left
        return outcome

    def _chosen_backup(self, backup: UUID | None, source: Server) -> str | None:
        if backup is None:
            newest = self.files.latest_of_kind(source.pk, BackupFile.Kind.DBS)
            return None if newest is None else str(newest.pk)
        file = self.files.find(backup)
        if (
            file is None
            or file.server_id != source.pk
            or file.kind != BackupFile.Kind.DBS
            or file.removed_at is not None
        ):
            raise _not_found("backup")
        return str(file.pk)

    def _source_version(self, version_id: UUID, source: Server) -> None:
        version = self.versions.find(version_id)
        if version is None or version.server_id != source.pk:
            raise _not_found("env_version")

    def _queue(self, action: str, target: Server, detail: Detail) -> AuditEvent:
        return JobQueue(self.user).queue_backup(
            action,
            server=target,
            target=target.name,
            detail=detail,
            send=lambda job: get_runner().submit(RedeployService().run, job.pk),
        )

    def _let_go(self, activity_id: int) -> None:
        entry = ActivityRepository().find_joined(activity_id)
        if entry is not None and entry.subject:
            TakeLock().release(UUID(entry.subject), activity_id)

    def _confirm(
        self,
        action: str,
        target: Server,
        detail: Detail,
        password: str,
        confirm_name: str,
    ) -> None:
        if not password:
            raise ValidationError(
                {"password": [ErrorDetail(PASSWORD_REQUIRED, code="required")]}
            )
        if confirm_name.strip() != target.name:
            raise ConfirmNameMismatch()
        try:
            AccountService(self.user).confirm_password(password)
        except (InvalidPassword, TooManyAttempts) as exc:
            self.activity.record(
                action,
                server=target,
                target=target.name,
                detail=detail,
                status=audit.FAILED,
                error_code=error_code_of(exc),
            )
            raise


def _planned(steps: tuple[str, ...], runs: list[str] | tuple[str, ...]) -> list[Detail]:
    return [
        {"step": step, "status": PENDING if step in runs else SKIPPED}
        for step in steps
    ]


def _has_material(step: str, detail: Detail) -> bool:
    if step == "env":
        return detail["env_version"] is not None
    if step == "restore":
        return detail["backup"] is not None
    return True


def _revertable(move: AuditEvent) -> bool:
    data = move.data or {}
    return (
        move.action == RUN
        and move.status == audit.FAILED
        and not data.get("rehearsal", True)
        and bool(data.get("revertable"))
    )


def _may_revert(detail: Detail, failed_step: str) -> bool:
    return (
        not detail["rehearsal"]
        and failed_step in CHANGING_STEPS
        and (
            detail.get("target_env_version") is not None
            or detail.get("safety_backup") is not None
        )
    )


def _failed_detail(detail: Detail, exc: APIException) -> Detail:
    if isinstance(exc, RemoteCommandFailed) and exc.output:
        return {**detail, "output": exc.output}
    return detail
