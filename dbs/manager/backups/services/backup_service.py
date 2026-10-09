from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, BinaryIO, cast
from uuid import UUID

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from rest_framework.exceptions import ErrorDetail, NotFound, ValidationError

from dbs import audit
from dbs.manager.accounts.exceptions import InvalidPassword, TooManyAttempts
from dbs.manager.accounts.services import AccountService
from dbs.manager.activity.services import ActivityService
from dbs.manager.backups.exceptions import BackupMissing, NotRestorable
from dbs.manager.backups.models import BackupFile
from dbs.manager.backups.repositories import BackupFileRepository
from dbs.manager.backups.services import vault_contexts
from dbs.manager.backups.services.actions import Action
from dbs.manager.backups.services.backup_run_service import BackupRunService
from dbs.manager.backups.services.job_queue import JobQueue
from dbs.manager.backups.storage import BackupStorage
from dbs.manager.common.exceptions import error_code_of
from dbs.manager.common.uploads import UploadTooLarge, upload_name
from dbs.manager.runner import get_runner
from dbs.manager.servers.services import ServerService
from dbs.manager.vault import open_stream, seal_stream
from dbs.models import AuditEvent

if TYPE_CHECKING:
    from django.contrib.auth.models import AnonymousUser, User

NAME_MAX_LENGTH: int = cast(int, BackupFile._meta.get_field("name").max_length)
INVALID_NAME = "Give the file a name, not only spaces or dots."
ACCOUNT_PASSWORD_REQUIRED = "Enter your own password to restore into the server."
SERVER_NAME_MISMATCH = "Type the server's name exactly as it is shown."


class Plaintext:
    def __init__(self, handle: BinaryIO, chunks: Iterator[bytes]) -> None:
        self.handle = handle
        self.chunks = chunks

    def __iter__(self) -> Iterator[bytes]:
        return self.chunks

    def close(self) -> None:
        self.handle.close()


@dataclass(frozen=True)
class Download:
    content: BinaryIO | Plaintext
    name: str
    size: int


class BackupService:
    def __init__(self, user: User | AnonymousUser | None) -> None:
        self.user: User | AnonymousUser | None = user
        self.files = BackupFileRepository()
        self.servers = ServerService(user)
        self.activity = ActivityService(user)
        self.jobs = JobQueue(user)
        self.storage = BackupStorage()

    def list(self, server_id: UUID) -> QuerySet[BackupFile]:
        return self.files.alive_for_server(server_id)

    def get(self, file_id: UUID) -> BackupFile:
        file = self.files.find(file_id)
        if file is None:
            raise NotFound()
        return file

    def download(self, file_id: UUID) -> Download:
        file = self.get(file_id)
        try:
            handle = self.storage.open_read(file.storage_path)
        except FileNotFoundError as exc:
            raise BackupMissing() from exc
        if file.sealed:
            download = Download(
                content=_plaintext(handle), name=file.name, size=file.size
            )
        else:
            download = Download(
                content=handle, name=file.name, size=os.fstat(handle.fileno()).st_size
            )
        self.activity.record(Action.DOWNLOAD, server=file.server, target=file.name)
        return download

    def upload(self, server_id: UUID, upload: UploadedFile) -> BackupFile:
        try:
            name = upload_name(upload.name or "", NAME_MAX_LENGTH)
            if name is None:
                raise ValidationError(
                    {"file": [ErrorDetail(INVALID_NAME, code="invalid_name")]}
                )
            if cast(int, upload.size) > settings.BACKUP_UPLOAD_MAX_BYTES:
                raise UploadTooLarge()
            server = self.servers.get(server_id)
            self.storage.directory(server.pk)
            stored_path = self.storage.unused_sealed_path(server.pk, name)
            with self.storage.writing(stored_path) as target:
                sealed = seal_stream(upload, target, context=vault_contexts.SEALED_FILE)
        finally:
            upload.close()
        try:
            with transaction.atomic():
                file = self.files.create(
                    created_by=cast("User | None", self.user),
                    server=server,
                    kind=BackupFile.Kind.UPLOADED,
                    name=name,
                    size=sealed.size,
                    sha256=sealed.sha256,
                    storage_path=stored_path,
                    sealed=True,
                    validation=BackupFile.Validation.STRUCTURE_OK,
                    validated_at=timezone.now(),
                )
                self.activity.record(
                    Action.UPLOAD,
                    server=server,
                    target=name,
                    detail={"size": file.size},
                )
        except BaseException:
            self.storage.remove(stored_path)
            raise
        return file

    def take(self, server_id: UUID) -> AuditEvent:
        server = self.servers.get(server_id)
        return self.jobs.queue_backup(
            Action.TAKE,
            server=server,
            target=server.name,
            send=lambda job: get_runner().submit(BackupRunService().take, job.pk),
        )

    def verify(self, file_id: UUID) -> AuditEvent:
        file = self.get(file_id)
        return self.jobs.queue(
            Action.VERIFY,
            server=file.server,
            target=file.name,
            send=lambda job: get_runner().submit(
                BackupRunService().verify, job.pk, file.pk
            ),
        )

    def restore(
        self,
        file_id: UUID,
        *,
        mode: str,
        rehearse: bool,
        account_password: str = "",
        server_name: str = "",
    ) -> AuditEvent:
        file = self.get(file_id)
        if file.kind != BackupFile.Kind.DBS:
            raise NotRestorable()
        server = self.servers.get(file.server_id)
        detail = {"backup": str(file.pk), "mode": mode, "rehearse": rehearse}
        if not rehearse:
            errors: dict[str, list[ErrorDetail]] = {}
            if not account_password:
                errors["account_password"] = [
                    ErrorDetail(ACCOUNT_PASSWORD_REQUIRED, code="required")
                ]
            if server_name.strip() != server.name:
                errors["server_name"] = [
                    ErrorDetail(SERVER_NAME_MISMATCH, code="name_mismatch")
                ]
            if errors:
                raise ValidationError(errors)
            try:
                AccountService(self.user).confirm_password(account_password)
            except (InvalidPassword, TooManyAttempts) as exc:
                self.activity.record(
                    Action.RESTORE,
                    server=server,
                    target=file.name,
                    detail=detail,
                    status=audit.FAILED,
                    error_code=error_code_of(exc),
                )
                raise
        return self.jobs.queue_backup(
            Action.RESTORE,
            server=server,
            target=file.name,
            detail=detail,
            send=lambda job: get_runner().submit(
                BackupRunService().restore, job.pk, file.pk
            ),
        )

    def delete(self, file_id: UUID) -> None:
        file = self.get(file_id)
        with transaction.atomic():
            self.files.soft_delete(file)
            self.activity.record(Action.DELETE, server=file.server, target=file.name)

    def undo_delete(self, file_id: UUID) -> BackupFile:
        file = self.files.find_including_deleted(file_id)
        if (
            file is None
            or not file.is_deleted
            or file.removed_at is not None
            or not self.storage.exists(file.storage_path)
        ):
            raise NotFound()
        with transaction.atomic():
            self.files.restore(file)
            self.activity.record(
                Action.UNDO_DELETE, server=file.server, target=file.name
            )
        return file


def _plaintext(handle: BinaryIO) -> Plaintext:
    try:
        return Plaintext(
            handle, open_stream(handle, context=vault_contexts.SEALED_FILE)
        )
    except BaseException:
        handle.close()
        raise
