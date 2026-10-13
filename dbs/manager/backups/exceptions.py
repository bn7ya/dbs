from __future__ import annotations

from rest_framework import status
from rest_framework.exceptions import APIException, NotFound


class BackupRunning(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "backup_running"
    default_detail = "A backup or restore of this server is already queued or running."


class BackupMissing(NotFound):
    default_code = "backup_missing"
    default_detail = "The backup file is no longer on disk."


class NotRestorable(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "not_restorable"
    default_detail = "Only a django-dbs backup can be restored."


class ArchiveMismatch(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_code = "archive_mismatch"
    default_detail = (
        "The archive that arrived is not the one the server made, so it was not kept."
    )


class BackupQuarantined(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "backup_quarantined"
    default_detail = (
        "The backup failed verification when it arrived, so it is kept aside and is "
        "never restored."
    )

    def __init__(
        self,
        detail: str | None = None,
        code: str | None = None,
        *,
        output: str = "",
        backup: str = "",
    ) -> None:
        super().__init__(detail, code)
        self.output: str = output
        self.backup: str = backup
