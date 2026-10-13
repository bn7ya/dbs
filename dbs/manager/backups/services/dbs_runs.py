from __future__ import annotations

import posixpath
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, cast

from django.utils import timezone

from dbs import validate_backup
from dbs.manager.activity.services import ActivityService
from dbs.manager.backups.models import BackupFile, BackupPlan
from dbs.manager.backups.repositories import BackupFileRepository
from dbs.manager.backups.storage import BackupStorage, Incoming, StoredFile
from dbs.manager.servers.exceptions import RemoteNotFound, StreamBroken
from dbs.manager.servers.gateways import DbsProfile, RemoteHost, ServerBackup
from dbs.manager.servers.models import Server
from dbs.models import AuditEvent
from dbs.naming import parse_backup_moment

QUARANTINE_SUFFIX = ".quarantined"
PROGRESS_EVERY_SECONDS = 1.0
FAILURE_MAX_LENGTH: int = cast(int, BackupFile._meta.get_field("failure").max_length)
COLLECTING = "collect"
STREAMING = "stream"
SHORT_ARRIVAL = "{received} of {expected} bytes arrived."
CHANGED_ARRIVAL = "The bytes that arrived are not the ones the server sent."


@dataclass
class DbsOutcome:
    streamed: BackupFile | None = None
    kept_on_server: bool = False
    pulled: list[BackupFile] = field(default_factory=list)
    released: list[str] = field(default_factory=list)

    @property
    def quarantined(self) -> list[BackupFile]:
        arrived = [*self.pulled, *([self.streamed] if self.streamed else [])]
        return [file for file in arrived if file.validation == BackupFile.Validation.FAILED]


class Progress:
    def __init__(self, job: AuditEvent, step: str) -> None:
        self.job = job
        self.step = step
        self.jobs = ActivityService(None)
        self.reported = 0.0

    def __call__(self, received: int) -> None:
        now = time.monotonic()
        if now - self.reported < PROGRESS_EVERY_SECONDS:
            return
        self.reported = now
        self.jobs.progress(
            self.job.pk, {**self.job.data, "step": self.step, "received": received}
        )


def moment_of(file: BackupFile) -> tuple[datetime, datetime]:
    named = parse_backup_moment(PurePosixPath(file.remote_path or file.name).name)
    return (named or file.created_at, file.created_at)


class DbsRun:
    def __init__(
        self,
        job: AuditEvent,
        server: Server,
        plan: BackupPlan | None,
        *,
        remote: RemoteHost,
        profile: DbsProfile,
        passphrase: str,
        prefix: str,
        keep_remote: int,
    ) -> None:
        self.job = job
        self.server = server
        self.plan = plan
        self.remote = remote
        self.profile = profile
        self.passphrase = passphrase
        self.prefix = prefix
        self.keep_remote = keep_remote
        self.files = BackupFileRepository()
        self.storage = BackupStorage()

    def run(self) -> DbsOutcome:
        outcome = DbsOutcome()
        self.storage.sweep_partials(self.server.pk)
        folder = self.remote.backup_folder(self.profile, self.server.remote_backup_dir)
        if self.profile.compose is None and folder:
            self.remote.sweep_partials(folder)
        outcome.pulled = self._collect(folder)
        try:
            outcome.streamed = self._stream(folder)
        except StreamBroken:
            outcome.kept_on_server = True
            return outcome
        outcome.released = self._release(folder)
        return outcome

    def _collect(self, folder: str) -> list[BackupFile]:
        waiting = self.remote.waiting_backups(self.profile, folder, self.prefix)
        recorded: dict[str, list[BackupFile]] = {}
        for file in self.files.recorded_at(self.server.pk, (b.path for b in waiting)):
            recorded.setdefault(file.remote_path, []).append(file)
        pulled = []
        for found in waiting:
            if self._held(found, recorded.get(found.path, [])):
                continue
            file = self._pull(found)
            if file is not None:
                pulled.append(file)
        return pulled

    def _held(self, found: ServerBackup, recorded: list[BackupFile]) -> bool:
        same_size = [file for file in recorded if _remote_size(file) == found.size]
        if not same_size:
            return False
        digest = self.remote.backup_sha256(self.profile, found.path)
        return any(file.sha256 == digest for file in same_size)

    def _pull(self, found: ServerBackup) -> BackupFile | None:
        with self.storage.receiving(self.server.pk) as incoming:
            try:
                self.remote.pull_backup(
                    self.profile, found.path, incoming, Progress(self.job, COLLECTING)
                )
            except RemoteNotFound:
                return None
            return self._register(
                incoming,
                name=found.name,
                remote_path=found.path,
                remote_size=found.size,
                remote_mtime=found.mtime,
            )

    def _stream(self, folder: str) -> BackupFile:
        with self.storage.receiving(self.server.pk) as incoming:
            streamed = self.remote.stream_dbs_backup(
                self.profile,
                passphrase=self.passphrase,
                prefix=self.prefix,
                folder=folder,
                sink=incoming,
                progress=Progress(self.job, STREAMING),
            )
            return self._register(
                incoming,
                name=streamed.name,
                remote_path=streamed.path,
                remote_size=streamed.size,
                expected_sha256=streamed.sha256,
            )

    def _register(
        self,
        incoming: Incoming,
        *,
        name: str,
        remote_path: str,
        remote_size: int,
        remote_mtime: datetime | None = None,
        expected_sha256: str = "",
    ) -> BackupFile:
        incoming.close()
        problem = self._problem(incoming, remote_size, expected_sha256)
        stored = self.storage.install(
            incoming, self.server.pk, f"{name}{QUARANTINE_SUFFIX}" if problem else name
        )
        validation = (
            BackupFile.Validation.FAILED if problem else BackupFile.Validation.VERIFIED
        )
        return self._record(
            stored,
            validation=validation,
            failure=problem[:FAILURE_MAX_LENGTH],
            remote_path=remote_path,
            remote_size=remote_size,
            remote_mtime=remote_mtime,
        )

    def _problem(self, incoming: Incoming, remote_size: int, expected: str) -> str:
        if incoming.size != remote_size:
            return SHORT_ARRIVAL.format(received=incoming.size, expected=remote_size)
        if expected and incoming.sha256 != expected:
            return CHANGED_ARRIVAL
        result = validate_backup(incoming.path, self.passphrase)
        if result.ok and result.decrypted_ok:
            return ""
        return result.summary()

    def _record(self, stored: StoredFile, **fields: Any) -> BackupFile:
        try:
            return self.files.create(
                created_by=self.job.actor,
                server=self.server,
                plan=self.plan,
                kind=BackupFile.Kind.DBS,
                name=PurePosixPath(stored.relative_path).name,
                size=stored.size,
                sha256=stored.sha256,
                storage_path=stored.relative_path,
                validated_at=timezone.now(),
                **fields,
            )
        except BaseException:
            self.storage.remove(stored.relative_path)
            raise

    def _release(self, folder: str) -> list[str]:
        copies = sorted(
            self.files.server_copies(self.server.pk, self.plan and self.plan.pk),
            key=moment_of,
            reverse=True,
        )[self.keep_remote :]
        if not copies:
            return []
        listed = {
            found.path: found
            for found in self.remote.waiting_backups(self.profile, folder, self.prefix)
        }
        released = []
        for file in copies:
            found = listed.get(file.remote_path)
            if found is None:
                if posixpath.dirname(file.remote_path) == folder:
                    self.files.update(file, remote_path="")
                continue
            if found.size != _remote_size(file):
                continue
            self.remote.remove_backup(self.profile, file.remote_path)
            self.files.update(file, remote_path="")
            released.append(found.name)
        return released


def _remote_size(file: BackupFile) -> int:
    return file.size if file.remote_size is None else file.remote_size
