from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import IO

from django.core.files.uploadedfile import UploadedFile
from django.core.files.uploadhandler import FileUploadHandler
from django.http import HttpRequest
from rest_framework import status
from rest_framework.exceptions import APIException

FORM_ALLOWANCE = 1024 * 1024
TEMPORARY_SUFFIX = ".upload"
FOLDER_SEPARATOR = re.compile(r"[/\\]")


class UploadTooLarge(APIException):
    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    default_code = "upload_too_large"
    default_detail = "The file is larger than this application accepts."


class SpooledUploadHandler(FileUploadHandler):
    def __init__(
        self,
        request: HttpRequest | None = None,
        *,
        limit: int,
        directory: Callable[[], Path],
    ) -> None:
        super().__init__(request)
        self.limit: int = limit
        self.directory: Callable[[], Path] = directory
        self.received: int = 0

    def handle_raw_input(
        self,
        input_data: IO[bytes],
        meta: dict[str, str],
        content_length: int,
        boundary: str,
        encoding: str | None = None,
    ) -> None:
        if content_length > self.limit + FORM_ALLOWANCE:
            input_data.read(0)
            raise UploadTooLarge()

    def new_file(
        self,
        field_name: str,
        file_name: str,
        content_type: str,
        content_length: int | None,
        charset: str | None = None,
        content_type_extra: dict[str, bytes] | None = None,
    ) -> None:
        super().new_file(
            field_name,
            file_name,
            content_type,
            content_length,
            charset,
            content_type_extra,
        )
        self.file: UploadedFile = UploadedFile(
            tempfile.NamedTemporaryFile(dir=self.directory(), suffix=TEMPORARY_SUFFIX),
            self.file_name,
            self.content_type,
            0,
            self.charset,
            self.content_type_extra,
        )

    def receive_data_chunk(self, raw_data: bytes, start: int) -> None:
        self.received += len(raw_data)
        if self.received > self.limit:
            self.upload_interrupted()
            raise UploadTooLarge()
        self.file.write(raw_data)

    def file_complete(self, file_size: int) -> UploadedFile:
        self.file.seek(0)
        self.file.size = file_size
        return self.file

    def upload_interrupted(self) -> None:
        if hasattr(self, "file"):
            self.file.close()


def upload_name(
    sent: str, max_length: int, length: Callable[[str], int] = len
) -> str | None:
    base = FOLDER_SEPARATOR.split(sent)[-1]
    name = "".join(character for character in base if character.isprintable()).strip()
    if name in {"", ".", ".."}:
        return None
    if length(name) <= max_length:
        return name
    stem, extension = os.path.splitext(name)
    extension = _cut(extension, max_length, length)
    return _cut(stem, max_length - length(extension), length) + extension


def utf8_length(text: str) -> int:
    return len(text.encode())


def _cut(text: str, room: int, length: Callable[[str], int]) -> str:
    shortest, longest = 0, len(text)
    while shortest < longest:
        middle = (shortest + longest + 1) // 2
        if length(text[:middle]) <= room:
            shortest = middle
        else:
            longest = middle - 1
    return text[:shortest]
