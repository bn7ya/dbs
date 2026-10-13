from __future__ import annotations

import datetime
import errno
import hashlib
import os
import re
import secrets
import stat
import time
from dataclasses import dataclass

from .exceptions import DBSError
from .naming import backup_filename, is_backup_name

CHUNK_SIZE = 1024 * 1024
FILE_MODE = 0o600
DIRECTORY_MODE = 0o700
PARTIAL_TOKEN_BYTES = 8
PARTIAL_STALE_SECONDS = 3600
LEGACY_PARTIAL_SUFFIX = ".part"
MAX_ORDINAL = 999
NO_HARD_LINKS = {errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.ENOSYS, errno.EXDEV}

_PARTIAL_NAME = re.compile(r"^\..+\.part-[0-9a-f]{%d}$" % (PARTIAL_TOKEN_BYTES * 2))


def partial_name(name: str) -> str:
    return f".{name}.part-{secrets.token_hex(PARTIAL_TOKEN_BYTES)}"


def is_partial_name(name: str) -> bool:
    if _PARTIAL_NAME.match(name):
        return True
    return name.endswith(LEGACY_PARTIAL_SUFFIX) and is_backup_name(
        name[: -len(LEGACY_PARTIAL_SUFFIX)]
    )


def is_stale(modified: float, now: float | None = None) -> bool:
    return (time.time() if now is None else now) - modified > PARTIAL_STALE_SECONDS


def sweep_partials(directory: str, *, now: float | None = None) -> list[str]:
    try:
        entries = list(os.scandir(directory))
    except OSError:
        return []
    removed = []
    for entry in entries:
        if not is_partial_name(entry.name):
            continue
        try:
            found = entry.stat(follow_symlinks=False)
        except OSError:
            continue
        if not stat.S_ISREG(found.st_mode) or not is_stale(found.st_mtime, now):
            continue
        try:
            os.remove(entry.path)
        except OSError:
            continue
        removed.append(entry.name)
    return sorted(removed)


def place_without_replacing(source: str, target: str) -> bool:
    try:
        os.link(source, target)
    except FileExistsError:
        return False
    except OSError as exc:
        if exc.errno not in NO_HARD_LINKS:
            raise
        if os.path.lexists(target):
            return False
        os.rename(source, target)
        return True
    os.unlink(source)
    return True


def install_backup(
    partial: str, directory: str, prefix: str, moment: datetime.datetime
) -> str:
    for ordinal in range(1, MAX_ORDINAL + 1):
        name = backup_filename(prefix, moment, ordinal)
        if place_without_replacing(partial, os.path.join(directory, name)):
            return name
    raise DBSError("Cannot find an unused backup filename for this second.")


def _private_directory(directory: str) -> None:
    os.makedirs(directory, mode=DIRECTORY_MODE, exist_ok=True)


@dataclass(frozen=True)
class TeeResult:
    name: str
    path: str
    size: int
    sha256: str
    stream_lost: bool

    def as_dict(self) -> dict:
        reported = {"name": self.name, "size": self.size, "sha256": self.sha256}
        if self.stream_lost:
            reported["kept_on_server"] = True
        return reported


class TeeSink:
    def __init__(
        self,
        stream,
        directory: str,
        prefix: str,
        *,
        moment: datetime.datetime | None = None,
    ):
        self.stream = stream
        self.directory = directory
        self.prefix = prefix
        self.moment = moment or datetime.datetime.now(datetime.timezone.utc)
        self.size = 0
        self.stream_lost = stream is None
        self._digest = hashlib.sha256()
        _private_directory(directory)
        self.partial = os.path.join(
            directory, partial_name(backup_filename(prefix, self.moment))
        )
        descriptor = os.open(
            self.partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE
        )
        self._file = os.fdopen(descriptor, "wb")

    def __enter__(self) -> "TeeSink":
        return self

    def __exit__(self, kind, value, traceback) -> None:
        if kind is not None:
            self.discard()

    def write(self, data) -> int:
        self._file.write(data)
        self._digest.update(data)
        self.size += len(data)
        self._send(data)
        return len(data)

    def write_all(self, data, chunk_size: int = CHUNK_SIZE) -> None:
        view = memoryview(data)
        for start in range(0, len(view), chunk_size):
            self.write(view[start : start + chunk_size])

    def finish(self) -> TeeResult:
        if not self.stream_lost:
            try:
                self.stream.flush()
            except (OSError, ValueError):
                self.stream_lost = True
        self._file.flush()
        os.fsync(self._file.fileno())
        self._file.close()
        name = install_backup(self.partial, self.directory, self.prefix, self.moment)
        return TeeResult(
            name=name,
            path=os.path.join(self.directory, name),
            size=self.size,
            sha256=self._digest.hexdigest(),
            stream_lost=self.stream_lost,
        )

    def discard(self) -> None:
        if not self._file.closed:
            self._file.close()
        try:
            os.remove(self.partial)
        except FileNotFoundError:
            pass

    def _send(self, data) -> None:
        if self.stream_lost:
            return
        try:
            self.stream.write(data)
        except (OSError, ValueError):
            self.stream_lost = True
