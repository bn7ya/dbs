from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest

from dbs.manager.backups.storage import BackupStorage
from dbs.manager.common.uploads import SpooledUploadHandler


class UploadHandler(SpooledUploadHandler):
    def __init__(self, request: HttpRequest | None = None) -> None:
        super().__init__(
            request,
            limit=settings.FILES_UPLOAD_MAX_BYTES,
            directory=BackupStorage().uploads_directory,
        )
