from __future__ import annotations

import hashlib
import os
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from itertools import count
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from uuid import UUID

from django.conf import settings

from dbs.tee import is_stale, place_without_replacing

DIRECTORY_MODE = 0o700
FILE_MODE = 0o600
SEALED_SUFFIX = ".sealed"
PARTIAL_SUFFIX = ".part"
INCOMING_PREFIX = ".incoming-"
UPLOADS_DIRECTORY = ".uploads"
STORED_NAME_MAX_BYTES = 200
DIGEST_CHUNK = 1024 * 1024


def sha256_of(handle: BinaryIO) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: handle.read(DIGEST_CHUNK), b""):
        digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class StoredFile:
    relative_path: str
    size: int
    sha256: str


class Incoming:
    def __init__(self, path: Path, handle: BinaryIO) -> None:
        self.path = path
        self.size = 0
        self._handle = handle
        self._digest = hashlib.sha256()

    def write(self, data: bytes) -> int:
        self._handle.write(data)
        self._digest.update(data)
        self.size += len(data)
        return len(data)

    @property
    def sha256(self) -> str:
        return self._digest.hexdigest()

    def close(self) -> None:
        if not self._handle.closed:
            self._handle.flush()
            os.fsync(self._handle.fileno())
            self._handle.close()


class BackupStorage:
    def __init__(self) -> None:
        self.root = Path(settings.BACKUP_STORAGE_DIR)

    def directory(self, server_id: UUID) -> Path:
        return self._private(self.root / str(server_id))

    def uploads_directory(self) -> Path:
        return self._private(self.root / UPLOADS_DIRECTORY)

    def remove_stale_uploads(self, before: datetime) -> None:
        uploads = self.root / UPLOADS_DIRECTORY
        if not uploads.is_dir():
            return
        for path in uploads.iterdir():
            if path.is_file() and path.stat().st_mtime < before.timestamp():
                path.unlink(missing_ok=True)

    def sweep_partials(self, server_id: UUID) -> list[str]:
        removed = []
        for path in self.directory(server_id).iterdir():
            if not path.name.endswith(PARTIAL_SUFFIX):
                continue
            try:
                found = path.lstat()
            except FileNotFoundError:
                continue
            if path.is_file() and is_stale(found.st_mtime):
                path.unlink(missing_ok=True)
                removed.append(path.name)
        return sorted(removed)

    @contextmanager
    def receiving(self, server_id: UUID) -> Iterator[Incoming]:
        path = self.directory(server_id) / (
            f"{INCOMING_PREFIX}{secrets.token_hex(8)}{PARTIAL_SUFFIX}"
        )
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE)
        incoming = Incoming(path, os.fdopen(descriptor, "wb"))
        try:
            yield incoming
        finally:
            incoming.close()
            path.unlink(missing_ok=True)

    def install(self, incoming: Incoming, server_id: UUID, name: str) -> StoredFile:
        incoming.close()
        directory = self.directory(server_id)
        chosen = next(
            candidate
            for candidate in _numbered(name)
            if place_without_replacing(str(incoming.path), str(directory / candidate))
        )
        (directory / chosen).chmod(FILE_MODE)
        return StoredFile(f"{server_id}/{chosen}", incoming.size, incoming.sha256)

    def sealed_path(self, server_id: UUID, name: str) -> str:
        return f"{server_id}/{name}{SEALED_SUFFIX}"

    def unused_sealed_path(self, server_id: UUID, name: str) -> str:
        stem = name.encode()[:STORED_NAME_MAX_BYTES].decode(errors="ignore")
        candidates = (
            self.sealed_path(server_id, stem if ordinal == 1 else f"{stem}-{ordinal}")
            for ordinal in count(1)
        )
        return next(path for path in candidates if not self.exists(path))

    @contextmanager
    def writing(self, relative_path: str) -> Iterator[BinaryIO]:
        final = self._absolute(relative_path)
        partial = final.with_name(final.name + PARTIAL_SUFFIX)
        os.close(os.open(final, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE))
        try:
            descriptor = os.open(
                partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, FILE_MODE
            )
            with os.fdopen(descriptor, "wb") as handle:
                yield handle
                handle.flush()
                os.fsync(handle.fileno())
            partial.chmod(FILE_MODE)
            partial.replace(final)
        except BaseException:
            partial.unlink(missing_ok=True)
            final.unlink(missing_ok=True)
            raise

    def open_read(self, relative_path: str) -> BinaryIO:
        return self._absolute(relative_path).open("rb")

    def exists(self, relative_path: str) -> bool:
        return self._absolute(relative_path).is_file()

    def remove(self, relative_path: str) -> None:
        self._absolute(relative_path).unlink(missing_ok=True)

    def _private(self, path: Path) -> Path:
        for directory in (self.root, path):
            directory.mkdir(mode=DIRECTORY_MODE, parents=True, exist_ok=True)
            directory.chmod(DIRECTORY_MODE)
        return path

    def _absolute(self, relative_path: str) -> Path:
        relative = PurePosixPath(relative_path)
        if (
            not relative.parts
            or relative.is_absolute()
            or ".." in relative.parts
            or "\x00" in relative_path
        ):
            raise ValueError(f"Not a path under the backup root: {relative_path!r}")
        return self.root / relative


def _numbered(name: str) -> Iterator[str]:
    kept = name.encode()[:STORED_NAME_MAX_BYTES].decode(errors="ignore")
    stem, dot, extension = kept.rpartition(".")
    if not dot or not stem:
        stem, extension = kept, ""
    suffix = f".{extension}" if extension else ""
    yield kept
    for ordinal in count(2):
        yield f"{stem}-{ordinal}{suffix}"

