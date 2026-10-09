from __future__ import annotations

import hashlib
import io
import os
import posixpath
import re
import stat
import tarfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone as dt_timezone
from pathlib import Path
from typing import BinaryIO

from dbs.manager.servers.exceptions import ArchiveFailed, RemoteNotFound
from dbs.manager.servers.gateways import (
    DbsProfile,
    FetchedBackup,
    RemoteArchive,
    RemoteFile,
    RestoreReport,
)
from dbs.naming import backup_filename
from tests.manager.servers.support import BACKUP_DIR, dbs_backup

SERVER_FILES = {
    "/srv/app/media/logo.png": b"\x89PNG not really",
    "/srv/app/media/uploads/report.pdf": b"%PDF-1.7 a report",
    "/etc/app.conf": b"setting=1\n",
}
ARCHIVED_PATHS = ["/srv/app/media", "/etc/app.conf"]
TAR_FAILURE = "tar: srv/app/missing: Cannot stat: No such file or directory"


@dataclass
class Take:
    profile: DbsProfile
    passphrase: str
    dest_dir: str
    prefix: str
    keep_remote: int


@dataclass
class Archive:
    paths: list[str]
    remote_dir: str
    name: str
    timeout: float
    content: bytes = b""


@dataclass
class Restore:
    profile: DbsProfile
    passphrase: str
    remote_dir: str
    flush: bool
    dry_run: bool
    content: bytes


RESTORED = RestoreReport(records=42, files=3, flushed=None, healed=False)


@dataclass
class Prune:
    remote_dir: str
    pattern: re.Pattern[str]
    keep: int


class BackupHost:
    def __init__(
        self,
        *,
        content: bytes | None = None,
        failure: Exception | None = None,
        root: Path | None = None,
        tar_status: int = 0,
        reported_sha256: str | None = None,
        restored: RestoreReport = RESTORED,
    ):
        self.content = content
        self.failure = failure
        self.root = root
        self.tar_status = tar_status
        self.reported_sha256 = reported_sha256
        self.restored = restored
        self.takes: list[Take] = []
        self.restores: list[Restore] = []
        self.archives: list[Archive] = []
        self.prunes: list[Prune] = []
        self.credentials = None

    def take_dbs_backup(
        self,
        *,
        profile: DbsProfile,
        passphrase: str,
        dest_dir: str,
        prefix: str,
        keep_remote: int,
    ) -> FetchedBackup:
        self.takes.append(Take(profile, passphrase, dest_dir, prefix, keep_remote))
        if self.failure is not None:
            raise self.failure
        name = backup_filename(prefix, ordinal=len(self.takes))
        path = Path(dest_dir) / name
        path.write_bytes(
            self.content if self.content is not None else dbs_backup(passphrase)
        )
        remote_path = f"{BACKUP_DIR}/{name}" if keep_remote else ""
        return FetchedBackup(local_path=str(path), remote_path=remote_path)

    def restore_dbs_backup(
        self,
        source: BinaryIO,
        *,
        profile: DbsProfile,
        passphrase: str,
        remote_dir: str,
        flush: bool,
        dry_run: bool,
    ) -> RestoreReport:
        content = source.read()
        self.restores.append(
            Restore(profile, passphrase, remote_dir, flush, dry_run, content)
        )
        if self.failure is not None:
            raise self.failure
        return self.restored

    def archive(
        self, paths: Sequence[str], remote_dir: str, name: str, timeout: float
    ) -> RemoteArchive:
        made = Archive(list(paths), remote_dir, name, timeout)
        self.archives.append(made)
        if self.failure is not None:
            raise self.failure
        if self.tar_status > 1:
            raise ArchiveFailed(output=TAR_FAILURE)
        target = self.on_server(posixpath.join(remote_dir, name))
        target.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(target, "w:gz") as tar:
            for path in paths:
                tar.add(self.on_server(path), arcname=path.lstrip("/"))
        made.content = target.read_bytes()
        return RemoteArchive(
            remote_path=posixpath.join(remote_dir, name),
            sha256=self.reported_sha256 or hashlib.sha256(made.content).hexdigest(),
            warning="files_changed" if self.tar_status == 1 else "",
        )

    @contextmanager
    def open_file(self, path: str) -> Iterator[BinaryIO]:
        with self.on_server(path).open("rb") as handle:
            yield handle

    def list_files(self, folder: str) -> list[RemoteFile]:
        if self.failure is not None:
            raise self.failure
        directory = self.on_server(folder)
        if not directory.is_dir():
            raise RemoteNotFound()
        files = []
        for entry in os.scandir(directory):
            found = entry.stat(follow_symlinks=False)
            if stat.S_ISREG(found.st_mode):
                files.append(
                    RemoteFile(
                        name=entry.name,
                        path=posixpath.join(folder, entry.name),
                        size=found.st_size,
                        mtime=datetime.fromtimestamp(
                            int(found.st_mtime), dt_timezone.utc
                        ),
                    )
                )
        return sorted(files, key=lambda file: file.name)

    def remove(self, path: str) -> None:
        self.on_server(path).unlink(missing_ok=True)

    def prune(self, remote_dir: str, pattern: re.Pattern[str], keep: int) -> None:
        self.prunes.append(Prune(remote_dir, pattern, keep))
        directory = self.on_server(remote_dir)
        matching = sorted(
            (entry for entry in os.scandir(directory) if pattern.fullmatch(entry.name)),
            key=lambda entry: (entry.stat().st_mtime_ns, entry.name),
        )
        for entry in matching[: max(len(matching) - keep, 0)]:
            self.remove(posixpath.join(remote_dir, entry.name))

    def on_server(self, path: str) -> Path:
        return self.root / path.lstrip("/")

    def remote_names(self) -> list[str]:
        directory = self.on_server(BACKUP_DIR)
        return sorted(os.listdir(directory)) if directory.is_dir() else []


def server_tree(root: Path) -> None:
    for path, content in SERVER_FILES.items():
        file = root / path.lstrip("/")
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(content)


def archived_files(content: bytes) -> dict[str, bytes]:
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as tar:
        files = [member for member in tar.getmembers() if member.isfile()]
        return {f"/{member.name}": tar.extractfile(member).read() for member in files}
