from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from datetime import datetime
from datetime import timezone as dt_timezone
from fnmatch import fnmatchcase
from itertools import count
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.exceptions import APIException, NotFound

from dbs import validate_backup
from dbs.manager.activity.services import ActivityService
from dbs.manager.backups.exceptions import ArchiveMismatch, BackupMissing, BackupRunning
from dbs.manager.backups.locks import TakeLock
from dbs.manager.backups.models import BackupFile, BackupPlan
from dbs.manager.backups.repositories import BackupFileRepository, BackupPlanRepository
from dbs.manager.backups.restore_modes import RestoreMode
from dbs.manager.backups.services import vault_contexts
from dbs.manager.backups.services.actions import Action
from dbs.manager.backups.services.plan_runs import last_run, run_detail
from dbs.manager.backups.storage import BackupStorage
from dbs.manager.common.uploads import upload_name
from dbs.manager.servers.exceptions import RemoteCommandFailed
from dbs.manager.servers.models import Server
from dbs.manager.servers.services import ServerConnectionService, ServerService
from dbs.manager.vault import VaultError, open_stream, seal_stream
from dbs.models import AuditEvent

if TYPE_CHECKING:
    from dbs.manager.servers.gateways import RemoteFile, RemoteHost

KEEP_REMOTE = 1
FALLBACK_PREFIX = "backup"
ARCHIVE_STAMP = "%Y%m%d-%H%M%S"
ARCHIVE_SUFFIX = ".tar.gz"
NO_MTIME = datetime.min.replace(tzinfo=dt_timezone.utc)
NAME_MAX_LENGTH: int = cast(int, BackupFile._meta.get_field("name").max_length)
FALLBACK_COLLECTED_NAME = "collected-file"

Detail = dict[str, Any]


def take_prefix(server: Server) -> str:
    return slugify(server.name) or FALLBACK_PREFIX


def plan_prefix(server: Server, plan: BackupPlan) -> str:
    return f"{take_prefix(server)}-{slugify(plan.name) or f'plan-{plan.pk.hex[:8]}'}"


def collected_name(listed: str) -> str:
    return upload_name(listed, NAME_MAX_LENGTH) or FALLBACK_COLLECTED_NAME


def archive_pattern(prefix: str) -> re.Pattern[str]:
    return re.compile(
        rf"{re.escape(prefix)}-\d{{8}}-\d{{6}}Z(?:-\d+)?{re.escape(ARCHIVE_SUFFIX)}"
    )


class BackupRunService:
    def __init__(self) -> None:
        self.jobs = ActivityService(None)
        self.files = BackupFileRepository()
        self.plans = BackupPlanRepository()
        self.storage = BackupStorage()
        self.locks = TakeLock()

    def take(self, activity_id: UUID) -> None:
        job = self.jobs.start(activity_id)
        if job is None:
            return
        try:
            self._run(job, self._take)
        finally:
            self.locks.release(UUID(job.subject), job.pk)

    def run_plan(self, activity_id: UUID, plan_id: UUID) -> None:
        job = self.jobs.start(activity_id)
        if job is None:
            return
        try:
            self._run(job, lambda job: self._run_plan(job, plan_id))
        finally:
            self.locks.release(UUID(job.subject), job.pk)
            self._remember(plan_id, activity_id)

    def verify(self, activity_id: UUID, file_id: UUID) -> None:
        job = self.jobs.start(activity_id)
        if job is None:
            return
        self._run(job, lambda job: self._verify(job, file_id))

    def restore(self, activity_id: UUID, file_id: UUID) -> None:
        job = self.jobs.start(activity_id)
        if job is None:
            return
        try:
            self._run(job, lambda job: self._restore(job, file_id))
        finally:
            self.locks.release(UUID(job.subject), job.pk)

    def _run(self, job: AuditEvent, work: Callable[[AuditEvent], Detail]) -> None:
        try:
            detail = work(job)
        except APIException as exc:
            self.jobs.fail(job.pk, exc, detail=_failure_detail(job, exc))
        except BaseException as exc:
            self.jobs.fail(job.pk, exc)
            raise
        else:
            self.jobs.succeed(job.pk, detail)

    def _take(self, job: AuditEvent) -> Detail:
        server_id: UUID = UUID(job.subject)
        if not self.locks.hold(server_id, job.pk):
            raise BackupRunning()
        server = ServerService(job.actor).get(server_id)
        file = self._back_up(
            job, server, prefix=take_prefix(server), keep_remote=KEEP_REMOTE, plan=None
        )
        return {"backup": str(file.pk), "size": file.size}

    def _run_plan(self, job: AuditEvent, plan_id: UUID) -> Detail:
        server_id: UUID = UUID(job.subject)
        if not self.locks.hold(server_id, job.pk):
            raise BackupRunning()
        plan = self.plans.find(plan_id)
        if plan is None:
            raise NotFound()
        server = ServerService(job.actor).get(server_id)
        if plan.kind == BackupPlan.Kind.COLLECT:
            outcome = self._collect(job, server, plan)
        elif plan.kind == BackupPlan.Kind.ARCHIVE:
            file, warning = self._archive(job, server, plan)
            outcome = {"backup": str(file.pk), "size": file.size}
            outcome |= {"warning": warning} if warning else {}
        else:
            file = self._back_up(
                job,
                server,
                prefix=plan_prefix(server, plan),
                keep_remote=plan.keep_remote,
                plan=plan,
            )
            outcome = {"backup": str(file.pk), "size": file.size}
        self._retain(job, plan)
        return {**run_detail(plan), **outcome}

    def _back_up(
        self,
        job: AuditEvent,
        server: Server,
        *,
        prefix: str,
        keep_remote: int,
        plan: BackupPlan | None,
    ) -> BackupFile:
        connections = ServerConnectionService(job.actor)
        with connections.open(server) as remote:
            fetched = remote.take_dbs_backup(
                profile=connections.dbs_profile(server),
                passphrase=connections.backup_passphrase(server),
                dest_dir=str(self.storage.directory(server.pk)),
                prefix=prefix,
                keep_remote=keep_remote,
            )
        stored = self.storage.keep(fetched.local_path)
        return self._record(
            job,
            server,
            plan,
            kind=BackupFile.Kind.DBS,
            name=Path(fetched.local_path).name,
            size=stored.size,
            sha256=stored.sha256,
            storage_path=stored.relative_path,
            remote_path=fetched.remote_path,
        )

    def _archive(
        self, job: AuditEvent, server: Server, plan: BackupPlan
    ) -> tuple[BackupFile, str]:
        prefix = plan_prefix(server, plan)
        self.storage.directory(server.pk)
        name = self._unused_archive_name(server, prefix)
        stored_path = self.storage.sealed_path(server.pk, name)
        with ServerConnectionService(job.actor).open(server) as remote:
            archive = remote.archive(
                plan.paths, server.remote_backup_dir, name, settings.BACKUP_EXEC_TIMEOUT
            )
            with (
                remote.open_file(archive.remote_path) as source,
                self.storage.writing(stored_path) as target,
            ):
                sealed = seal_stream(source, target, context=vault_contexts.SEALED_FILE)
                if sealed.sha256 != archive.sha256:
                    raise ArchiveMismatch()
            try:
                remote.prune(
                    server.remote_backup_dir, archive_pattern(prefix), plan.keep_remote
                )
            except BaseException:
                self.storage.remove(stored_path)
                raise
        file = self._record(
            job,
            server,
            plan,
            kind=BackupFile.Kind.ARCHIVE,
            name=name,
            size=sealed.size,
            sha256=sealed.sha256,
            storage_path=stored_path,
            sealed=True,
            remote_path=archive.remote_path if plan.keep_remote else "",
        )
        return file, archive.warning

    def _collect(self, job: AuditEvent, server: Server, plan: BackupPlan) -> Detail:
        self.storage.directory(server.pk)
        collected = skipped = size = 0
        with ServerConnectionService(job.actor).open(server) as remote:
            matching = [
                found
                for found in remote.list_files(plan.paths[0])
                if fnmatchcase(found.name, plan.pattern)
            ]
            seen = set(
                self.files.collected_from(plan.pk, (found.path for found in matching))
            )
            for found in sorted(
                matching, key=lambda found: (found.mtime or NO_MTIME, found.name)
            ):
                if (found.path, found.size, found.mtime) in seen:
                    file = None
                else:
                    file = self._collect_file(job, server, plan, remote, found)
                if file is None:
                    skipped += 1
                    continue
                collected += 1
                size += file.size
        return {"collected": collected, "skipped": skipped, "size": size}

    def _collect_file(
        self,
        job: AuditEvent,
        server: Server,
        plan: BackupPlan,
        remote: RemoteHost,
        found: RemoteFile,
    ) -> BackupFile | None:
        name = collected_name(found.name)
        stored_path = self.storage.unused_sealed_path(server.pk, name)
        with (
            remote.open_file(found.path) as source,
            self.storage.writing(stored_path) as target,
        ):
            sealed = seal_stream(source, target, context=vault_contexts.SEALED_FILE)
        if found.size is not None and sealed.size != found.size:
            self.storage.remove(stored_path)
            return None
        return self._record(
            job,
            server,
            plan,
            kind=BackupFile.Kind.COLLECTED,
            name=name,
            size=sealed.size,
            sha256=sealed.sha256,
            storage_path=stored_path,
            sealed=True,
            remote_path=found.path,
            remote_size=found.size,
            remote_mtime=found.mtime,
        )

    def _unused_archive_name(self, server: Server, prefix: str) -> str:
        stamp = timezone.now().strftime(ARCHIVE_STAMP)
        candidates = (
            f"{prefix}-{stamp}Z{'' if ordinal == 1 else f'-{ordinal}'}{ARCHIVE_SUFFIX}"
            for ordinal in count(1)
        )
        return next(
            name
            for name in candidates
            if not self.storage.exists(self.storage.sealed_path(server.pk, name))
        )

    def _record(
        self,
        job: AuditEvent,
        server: Server,
        plan: BackupPlan | None,
        *,
        storage_path: str,
        **fields: Any,
    ) -> BackupFile:
        try:
            return self.files.create(
                created_by=job.actor,
                server=server,
                plan=plan,
                storage_path=storage_path,
                validation=BackupFile.Validation.STRUCTURE_OK,
                validated_at=timezone.now(),
                **fields,
            )
        except BaseException:
            self.storage.remove(storage_path)
            raise

    def _retain(self, job: AuditEvent, plan: BackupPlan) -> None:
        stale = list(self.files.alive_for_plan(plan.pk)[plan.keep :])
        if not stale:
            return
        with transaction.atomic():
            for file in stale:
                self.files.soft_delete(file)
            ActivityService(job.actor).record(
                Action.RETENTION,
                server=plan.server,
                target=plan.name,
                detail={"removed": [file.name for file in stale], "plan": plan.name},
            )

    def _restore(self, job: AuditEvent, file_id: UUID) -> Detail:
        server_id: UUID = UUID(job.subject)
        if not self.locks.hold(server_id, job.pk):
            raise BackupRunning()
        file = self.files.find_including_deleted(file_id)
        if file is None or file.removed_at is not None:
            raise BackupMissing()
        server = ServerService(job.actor).get(server_id)
        connections = ServerConnectionService(job.actor)
        try:
            handle = self.storage.open_read(file.storage_path)
        except FileNotFoundError as exc:
            raise BackupMissing() from exc
        with handle, connections.open(server) as remote:
            report = remote.restore_dbs_backup(
                handle,
                profile=connections.dbs_profile(server),
                passphrase=connections.backup_passphrase(server),
                remote_dir=server.remote_backup_dir,
                flush=job.data["mode"] == RestoreMode.REPLACE,
                dry_run=job.data["rehearse"],
            )
        outcome: Detail = {
            "records": report.records,
            "files": report.files,
            "flushed": report.flushed,
            "healed": report.healed,
        }
        if report.copy_left:
            outcome["copy_left"] = report.copy_left
        return {**job.data, **outcome}

    def _remember(self, plan_id: UUID, activity_id: UUID) -> None:
        plan = self.plans.find(plan_id)
        if plan is not None:
            self.plans.update(plan, **last_run(self.jobs.get(activity_id)))

    def _verify(self, job: AuditEvent, file_id: UUID) -> Detail:
        file = self.files.find_including_deleted(file_id)
        if file is None or file.removed_at is not None:
            raise BackupMissing()
        intact = self._opens_whole(file) if file.sealed else self._decrypts(job, file)
        validation = (
            BackupFile.Validation.VERIFIED if intact else BackupFile.Validation.FAILED
        )
        self.files.update(file, validation=validation, validated_at=timezone.now())
        return {"validation": validation}

    def _decrypts(self, job: AuditEvent, file: BackupFile) -> bool:
        passphrase = ServerConnectionService(job.actor).backup_passphrase(file.server)
        try:
            with self.storage.open_read(file.storage_path) as handle:
                data = handle.read()
        except FileNotFoundError as exc:
            raise BackupMissing() from exc
        result = validate_backup(data, passphrase)
        decrypts: bool = result.ok and result.decrypted_ok
        return decrypts

    def _opens_whole(self, file: BackupFile) -> bool:
        digest = hashlib.sha256()
        try:
            with self.storage.open_read(file.storage_path) as handle:
                for chunk in open_stream(handle, context=vault_contexts.SEALED_FILE):
                    digest.update(chunk)
        except FileNotFoundError as exc:
            raise BackupMissing() from exc
        except VaultError:
            return False
        return digest.hexdigest() == file.sha256


def _failure_detail(job: AuditEvent, exc: APIException) -> Detail | None:
    if isinstance(exc, RemoteCommandFailed) and exc.output:
        return {**job.data, "output": exc.output}
    return None
