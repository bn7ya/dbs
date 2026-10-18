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
from dbs.manager.backups.exceptions import (
    BackupMissing,
    BackupQuarantined,
    NotRestorable,
)
from dbs.manager.backups.models import BackupFile
from dbs.manager.backups.repositories import BackupFileRepository
from dbs.manager.backups.services import vault_contexts
from dbs.manager.backups.services.actions import Action
from dbs.manager.backups.services.backup_run_service import BackupRunService
from dbs.manager.backups.services.job_queue import JobQueue
from dbs.manager.backups.storage import BackupStorage
from dbs.manager.common import tickets
from dbs.manager.common.exceptions import error_code_of
from dbs.manager.common.uploads import UploadTooLarge, upload_name
from dbs.manager.runner import get_runner
from dbs.manager.servers.exceptions import PassphraseMissing
from dbs.manager.applications.services import ApplicationService
from dbs.manager.vault import open_stream, seal_stream
from dbs.manager.permissions import Capability, requires
from dbs.models import AuditEvent

if TYPE_CHECKING:
    from django.contrib.auth.models import AnonymousUser, User

NAME_MAX_LENGTH: int = cast(int, BackupFile._meta.get_field("name").max_length)
INVALID_NAME = "Give the file a name, not only spaces or dots."
ACCOUNT_PASSWORD_REQUIRED = "Enter your own password to restore into the application."
DOWNLOAD_PASSWORD_REQUIRED = (
    "Enter your own password to download a file the manager keeps encrypted."
)
DELETE_PASSWORD_REQUIRED = "Enter your own password to delete a backup."
APPLICATION_NAME_MISMATCH = "Type the application's name exactly as it is shown."


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
        self.applications = ApplicationService(user)
        self.activity = ActivityService(user)
        self.jobs = JobQueue(user)
        self.storage = BackupStorage()

    def list(self, application_id: UUID | None = None) -> QuerySet[BackupFile]:
        if application_id is None:
            return self.files.alive()
        return self.files.alive_for_application(application_id)

    def get(self, file_id: UUID) -> BackupFile:
        file = self.files.find(file_id)
        if file is None:
            raise NotFound()
        return file

    @requires(Capability.BACKUPS_DOWNLOAD)
    def download(
        self, file_id: UUID, account_password: str = "", ticket: str = ""
    ) -> Download:
        file = self.get(file_id)
        if file.sealed:
            self._unlock(file, account_password, ticket)
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
        self.activity.record(Action.DOWNLOAD, subject=file.application, target=file.name)
        return download

    @requires(Capability.BACKUPS_DOWNLOAD)
    def download_ticket(self, file_id: UUID, account_password: str = "") -> str:
        file = self.get(file_id)
        if not file.sealed:
            return ""
        _require_password(account_password, DOWNLOAD_PASSWORD_REQUIRED)
        self._confirm_password(file, Action.DOWNLOAD, account_password)
        return tickets.issue(self.user, _download_subject(file))

    @requires(Capability.BACKUPS_UPLOAD)
    def upload(self, application_id: UUID, upload: UploadedFile) -> BackupFile:
        try:
            name = upload_name(upload.name or "", NAME_MAX_LENGTH)
            if name is None:
                raise ValidationError(
                    {"file": [ErrorDetail(INVALID_NAME, code="invalid_name")]}
                )
            if cast(int, upload.size) > settings.BACKUP_UPLOAD_MAX_BYTES:
                raise UploadTooLarge()
            application = self.applications.get(application_id)
            self.storage.directory(application.pk)
            stored_path = self.storage.unused_sealed_path(application.pk, name)
            with self.storage.writing(stored_path) as target:
                sealed = seal_stream(upload, target, context=vault_contexts.SEALED_FILE)
        finally:
            upload.close()
        try:
            with transaction.atomic():
                file = self.files.create(
                    created_by=cast("User | None", self.user),
                    application=application,
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
                    subject=application,
                    target=name,
                    detail={"size": file.size},
                )
        except BaseException:
            self.storage.remove(stored_path)
            raise
        return file

    @requires(Capability.BACKUPS_TAKE)
    def take(self, application_id: UUID) -> AuditEvent:
        application = self.applications.get(application_id)
        return self.jobs.queue_backup(
            Action.TAKE,
            application=application,
            target=application.name,
            send=lambda job: get_runner().submit(BackupRunService().take, job.pk),
        )

    @requires(Capability.BACKUPS_VERIFY)
    def verify(self, file_id: UUID) -> AuditEvent:
        file = self.get(file_id)
        return self.jobs.queue(
            Action.VERIFY,
            application=file.application,
            target=file.name,
            send=lambda job: get_runner().submit(
                BackupRunService().verify, job.pk, file.pk
            ),
        )

    @requires(Capability.BACKUPS_RESTORE)
    def restore(
        self,
        file_id: UUID,
        *,
        mode: str,
        rehearse: bool,
        account_password: str = "",
        application_name: str = "",
        target_application: UUID | None = None,
    ) -> AuditEvent:
        file = self.get(file_id)
        if file.kind != BackupFile.Kind.DBS:
            raise NotRestorable()
        if file.failure:
            raise BackupQuarantined()
        source = self.applications.get(file.application_id)
        target = (
            source
            if target_application is None
            else self.applications.get(target_application)
        )
        detail = {"backup": str(file.pk), "mode": mode, "rehearse": rehearse}
        if target.pk != source.pk:
            detail["source_application"] = str(source.pk)
            detail["target_application"] = str(target.pk)
        if not source.has_backup_passphrase:
            raise PassphraseMissing()
        if not rehearse:
            errors: dict[str, list[ErrorDetail]] = {}
            if not account_password:
                errors["account_password"] = [
                    ErrorDetail(ACCOUNT_PASSWORD_REQUIRED, code="required")
                ]
            if application_name.strip() != target.name:
                errors["application_name"] = [
                    ErrorDetail(APPLICATION_NAME_MISMATCH, code="name_mismatch")
                ]
            if errors:
                raise ValidationError(errors)
            try:
                AccountService(self.user).confirm_password(account_password)
            except (InvalidPassword, TooManyAttempts) as exc:
                self.activity.record(
                    Action.RESTORE,
                    subject=target,
                    target=file.name,
                    detail=detail,
                    status=audit.FAILED,
                    error_code=error_code_of(exc),
                )
                raise
        return self.jobs.queue_backup(
            Action.RESTORE,
            application=target,
            target=file.name,
            detail=detail,
            send=lambda job: get_runner().submit(
                BackupRunService().restore, job.pk, file.pk
            ),
        )

    @requires(Capability.BACKUPS_DELETE)
    def delete(self, file_id: UUID, account_password: str = "") -> None:
        file = self.get(file_id)
        _require_password(account_password, DELETE_PASSWORD_REQUIRED)
        self._confirm_password(file, Action.DELETE, account_password)
        with transaction.atomic():
            self.files.soft_delete(file)
            self.activity.record(Action.DELETE, subject=file.application, target=file.name)

    @requires(Capability.BACKUPS_DELETE)
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
                Action.UNDO_DELETE, subject=file.application, target=file.name
            )
        return file

    def _unlock(self, file: BackupFile, account_password: str, ticket: str) -> None:
        if ticket and tickets.redeem(ticket, self.user, _download_subject(file)):
            return
        _require_password(account_password, DOWNLOAD_PASSWORD_REQUIRED)
        self._confirm_password(file, Action.DOWNLOAD, account_password)

    def _confirm_password(
        self, file: BackupFile, action: str, account_password: str
    ) -> None:
        try:
            AccountService(self.user).confirm_password(account_password)
        except (InvalidPassword, TooManyAttempts) as exc:
            self.activity.record(
                action,
                subject=file.application,
                target=file.name,
                status=audit.FAILED,
                error_code=error_code_of(exc),
            )
            raise


def _require_password(account_password: str, message: str) -> None:
    if not account_password:
        raise ValidationError(
            {"account_password": [ErrorDetail(message, code="required")]}
        )


def _download_subject(file: BackupFile) -> str:
    return f"backup:{file.pk}"


def _plaintext(handle: BinaryIO) -> Plaintext:
    try:
        return Plaintext(
            handle, open_stream(handle, context=vault_contexts.SEALED_FILE)
        )
    except BaseException:
        handle.close()
        raise
