from __future__ import annotations

from typing import Any
from uuid import UUID

from django.conf import settings
from rest_framework.exceptions import APIException, ErrorDetail, ValidationError

from dbs import audit
from dbs.manager.accounts.exceptions import InvalidPassword, TooManyAttempts
from dbs.manager.accounts.services import AccountService
from dbs.manager.activity.services import ActivityService
from dbs.manager.backups.exceptions import BackupMissing, BackupRunning
from dbs.manager.backups.locks import TakeLock
from dbs.manager.backups.models import BackupFile
from dbs.manager.backups.repositories import BackupFileRepository
from dbs.manager.backups.services import vault_contexts
from dbs.manager.backups.services.job_queue import JobQueue
from dbs.manager.backups.storage import BackupStorage
from dbs.manager.common.exceptions import error_code_of
from dbs.manager.envfiles.repositories import EnvVersionRepository
from dbs.manager.envfiles.services import EnvFileService
from dbs.manager.redeploy.exceptions import (
    ConfirmNameMismatch,
    SameServer,
    TargetNotReady,
)
from dbs.manager.runner import get_runner
from dbs.manager.servers.exceptions import PassphraseMissing, RemoteCommandFailed
from dbs.manager.servers.services import ServerConnectionService, ServerService
from dbs.manager.vault import open_stream

RUN = "redeploy.run"
STEPS = ("check", "env", "migrate", "restore", "archives", "final_check")
REHEARSAL_STEPS = ("check", "restore")
PENDING = "pending"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
SKIPPED = "skipped"
NOT_FOUND = "Choose one of the source server's own files."
PASSWORD_REQUIRED = "Enter your own password to redeploy for real."


def _not_found(field: str) -> ValidationError:
    return ValidationError({field: [ErrorDetail(NOT_FOUND, code="not_found")]})


class ChunkReader:
    def __init__(self, chunks):
        self.chunks = iter(chunks)
        self.buffer = b""

    def read(self, size: int = -1) -> bytes:
        while size < 0 or len(self.buffer) < size:
            chunk = next(self.chunks, None)
            if chunk is None:
                break
            self.buffer += chunk
        if size < 0:
            size = len(self.buffer)
        piece, self.buffer = self.buffer[:size], self.buffer[size:]
        return piece


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
        backup: UUID,
        env_version: UUID | None = None,
        archives: list[UUID] | tuple = (),
        migrate: bool = False,
        flush: bool = False,
        rehearsal: bool = True,
        password: str = "",
        confirm_name: str = "",
    ) -> Any:
        source = self.servers.get(source_server)
        target = self.servers.get(target_server)
        if source.pk == target.pk:
            raise SameServer()
        self._source_file(backup, source, BackupFile.Kind.DBS, "backup")
        for archive in archives:
            self._source_file(archive, source, BackupFile.Kind.ARCHIVE, "archives")
        if env_version is not None:
            version = self.versions.find(env_version)
            if version is None or version.server_id != source.pk:
                raise _not_found("env_version")
        if not source.has_backup_passphrase:
            raise PassphraseMissing()
        detail = {
            "source_server": str(source.pk),
            "target_server": str(target.pk),
            "backup": str(backup),
            "env_version": None if env_version is None else str(env_version),
            "archives": [str(archive) for archive in archives],
            "migrate": migrate,
            "flush": flush,
            "rehearsal": rehearsal,
        }
        detail["steps"] = [
            {"step": step, "status": PENDING if _runs(step, detail) else SKIPPED}
            for step in STEPS
        ]
        if not rehearsal:
            self._confirm(target, detail, password, confirm_name)
        return JobQueue(self.user).queue_backup(
            RUN,
            server=target,
            target=target.name,
            detail=detail,
            send=lambda job: get_runner().submit(RedeployService().run, job.pk),
        )

    def run(self, activity_id: int) -> None:
        jobs = ActivityService(None)
        job = jobs.start(activity_id)
        if job is None:
            return
        target_id = UUID(job.subject)
        locks = TakeLock()
        detail = dict(job.data)
        try:
            if not locks.hold(target_id, job.pk):
                raise BackupRunning()
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

    def _steps(self, job: Any, detail: dict[str, Any], target_id: UUID) -> None:
        actor = job.actor
        target = ServerService(actor).get(target_id)
        jobs = ActivityService(None)
        for step in detail["steps"]:
            if step["status"] == SKIPPED:
                continue
            step["status"] = RUNNING
            jobs.progress(job.pk, detail)
            try:
                with ActivityService(actor).track(
                    f"redeploy.{step['step']}", server=target, target=target.name
                ) as entry:
                    entry.detail = self._step(step["step"], detail, target, actor)
            except BaseException:
                step["status"] = FAILED
                for later in detail["steps"]:
                    if later["status"] == PENDING:
                        later["status"] = SKIPPED
                raise
            step["status"] = SUCCEEDED
            jobs.progress(job.pk, detail)

    def _step(
        self, name: str, detail: dict[str, Any], target: Any, actor: Any
    ) -> dict[str, Any]:
        if name in ("check", "final_check"):
            return self._check(target, actor)
        if name == "env":
            version = EnvFileService(actor).copy_to(UUID(detail["env_version"]), target)
            return {"version": str(version.pk)}
        if name == "migrate":
            return self._migrate(target, actor)
        if name == "restore":
            return self._restore(detail, target, actor)
        return self._extract(detail, target, actor)

    def _check(self, target: Any, actor: Any) -> dict[str, Any]:
        checked = ServerService(actor).check(target.pk)
        report = checked.last_check_report or {}
        if (
            report.get("dbs_version") is None
            or report.get("backup_command") is not True
        ):
            raise TargetNotReady()
        return {"status": checked.last_check_status}

    def _migrate(self, target: Any, actor: Any) -> dict[str, Any]:
        connections = ServerConnectionService(actor)
        profile = connections.dbs_profile(target)
        env = (
            {"DJANGO_SETTINGS_MODULE": profile.settings_module}
            if profile.settings_module
            else None
        )
        with connections.open(target) as remote:
            result = remote.run(
                [profile.python, profile.manage, "migrate", "--noinput"],
                cwd=profile.project_dir,
                env=env,
                timeout=settings.BACKUP_EXEC_TIMEOUT,
            )
        if not result.ok:
            raise RemoteCommandFailed(
                output=f"{result.stdout}\n{result.stderr}".strip()[-500:]
            )
        return {}

    def _restore(
        self, detail: dict[str, Any], target: Any, actor: Any
    ) -> dict[str, Any]:
        file = self.files.find_including_deleted(UUID(detail["backup"]))
        if file is None or file.removed_at is not None:
            raise BackupMissing()
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
                flush=detail["flush"],
                dry_run=detail["rehearsal"],
            )
        outcome = {
            "records": report.records,
            "files": report.files,
            "flushed": report.flushed,
            "healed": report.healed,
        }
        if report.copy_left:
            outcome["copy_left"] = report.copy_left
        return outcome

    def _extract(
        self, detail: dict[str, Any], target: Any, actor: Any
    ) -> dict[str, Any]:
        storage = BackupStorage()
        extracted = 0
        with ServerConnectionService(actor).open(target) as remote:
            for archive_id in detail["archives"]:
                file = self.files.find_including_deleted(UUID(archive_id))
                if file is None or file.removed_at is not None:
                    raise BackupMissing()
                try:
                    handle = storage.open_read(file.storage_path)
                except FileNotFoundError as exc:
                    raise BackupMissing() from exc
                with handle:
                    chunks = open_stream(handle, context=vault_contexts.SEALED_FILE)
                    remote.extract_archive(
                        ChunkReader(chunks),
                        target.remote_backup_dir,
                        settings.BACKUP_EXEC_TIMEOUT,
                    )
                extracted += 1
        return {"extracted": extracted}

    def _source_file(self, file_id: UUID, source: Any, kind: str, field: str) -> None:
        file = self.files.find(file_id)
        if (
            file is None
            or file.server_id != source.pk
            or file.kind != kind
            or file.removed_at is not None
        ):
            raise _not_found(field)

    def _confirm(
        self, target: Any, detail: dict[str, Any], password: str, confirm_name: str
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
                RUN,
                server=target,
                target=target.name,
                detail=detail,
                status=audit.FAILED,
                error_code=error_code_of(exc),
            )
            raise


def _runs(step: str, detail: dict[str, Any]) -> bool:
    if detail["rehearsal"]:
        return step in REHEARSAL_STEPS
    if step == "env":
        return detail["env_version"] is not None
    if step == "migrate":
        return detail["migrate"]
    if step == "archives":
        return bool(detail["archives"])
    return True


def _failed_detail(detail: dict[str, Any], exc: APIException) -> dict[str, Any]:
    if isinstance(exc, RemoteCommandFailed) and exc.output:
        return {**detail, "output": exc.output}
    return detail
