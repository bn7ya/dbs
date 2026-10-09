from __future__ import annotations

import errno
import functools
import os
import stat
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.contrib.auth.models import Group
from paramiko import SFTPAttributes

from dbs import create_backup
from dbs.crypto.kdf import KDFParams
from dbs.manager.servers.exceptions import RemoteCommandFailed
from dbs.manager.servers.services.server_service import DBS_VERSION

PASSWORD = "correct-horse-battery-staple"
SSH_PASSWORD = "ssh-password-6d1f0c2e"
KEY_PASSPHRASE = "key-passphrase-93ab7e"
BACKUP_PASSPHRASE = "backup-passphrase-41c7d9"

PYTHON = "/srv/app/.venv/bin/python"
PROJECT_DIR = "/srv/app"
ENV_PATH = "/srv/app/.env"
MEDIA_ROOT = "/srv/app/media"
BACKUP_DIR = "/var/backups/dbs"
SETTINGS_MODULE = "config.settings.prod"


def host_key_line() -> str:
    public = Ed25519PrivateKey.generate().public_key()
    return public.public_bytes(
        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
    ).decode()


def private_key_text() -> str:
    return (
        Ed25519PrivateKey.generate()
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.OpenSSH,
            serialization.NoEncryption(),
        )
        .decode()
    )


@functools.cache
def dbs_backup(passphrase: str) -> bytes:
    return create_backup(
        passphrase,
        models=[Group],
        kdf_params=KDFParams(time_cost=1, memory_cost=8, parallelism=1),
    )


def body_line(private_key: str) -> str:
    return private_key.splitlines()[1]


@dataclass
class Result:
    exit_status: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.exit_status == 0


class FakeRemote:
    def __init__(
        self,
        *,
        answers: Mapping[tuple[str, ...], Result | Exception],
        paths: set[str],
        unreadable: frozenset[str] = frozenset(),
    ) -> None:
        self.answers = answers
        self.paths = paths
        self.unreadable = unreadable
        self.runs: list[dict] = []
        self.credentials = None

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        stdin_line: str | None = None,
        timeout: float | None = None,
    ) -> Result:
        self.runs.append({"argv": list(argv), "cwd": cwd, "env": env})
        answer = self.answers.get(tuple(argv), Result(127, "", "not found"))
        if isinstance(answer, Exception):
            raise answer
        return answer

    def exists(self, path: str) -> bool:
        if path in self.unreadable:
            raise RemoteCommandFailed()
        return path in self.paths


def healthy_remote() -> FakeRemote:
    return FakeRemote(
        answers={
            ("uname", "-sr"): Result(0, "Linux 6.1.0-18-amd64\n"),
            (PYTHON, "-c", DBS_VERSION): Result(0, "0.4.0\n"),
            (PYTHON, "manage.py", "dbs_backup", "--help"): Result(
                0, "usage: dbs_backup\n"
            ),
        },
        paths={ENV_PATH, MEDIA_ROOT, BACKUP_DIR},
    )


def connecting_to(remote: FakeRemote):

    @contextmanager
    def connect(credentials) -> Iterator[FakeRemote]:
        remote.credentials = credentials
        yield remote

    return connect


def refusing_with(error: Exception):

    def connect(credentials):
        raise error

    return connect


NOT_THERE = {errno.ENOENT, errno.ENOTDIR, errno.ELOOP, errno.EBADF}
REFUSED = {errno.EACCES, errno.EPERM}


@contextmanager
def as_sftp_server() -> Iterator[None]:
    try:
        yield
    except OSError as exc:
        if exc.errno in NOT_THERE:
            raise FileNotFoundError(errno.ENOENT, "No such file") from None
        if exc.errno in REFUSED:
            raise PermissionError(errno.EACCES, "Permission denied") from None
        raise OSError("Failure") from None


def attributes(found: os.stat_result, filename: str | None = None) -> SFTPAttributes:
    answer = SFTPAttributes.from_stat(found, filename)
    answer.st_atime, answer.st_mtime = int(found.st_atime), int(found.st_mtime)
    return answer


class SftpChannel:
    def __init__(self) -> None:
        self.timeout = None

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout


class LocalFile:
    def __init__(self, descriptor: int, mode: str) -> None:
        self.file = os.fdopen(descriptor, mode)
        self.prefetched = False
        self.pipelined = False

    def prefetch(self) -> None:
        self.prefetched = True

    def read(self, size: int = -1) -> bytes:
        with as_sftp_server():
            return self.file.read(size)

    def readv(self, chunks) -> Iterator[bytes]:
        for offset, size in chunks:
            with as_sftp_server():
                self.file.seek(offset)
                yield self.file.read(size)

    def write(self, data: bytes) -> None:
        with as_sftp_server():
            self.file.write(data)

    def set_pipelined(self, pipelined: bool = True) -> None:
        self.pipelined = pipelined

    def flush(self) -> None:
        with as_sftp_server():
            self.file.flush()

    def stat(self) -> SFTPAttributes:
        with as_sftp_server():
            return attributes(os.fstat(self.file.fileno()))

    def chmod(self, mode: int) -> None:
        with as_sftp_server():
            os.fchmod(self.file.fileno(), mode)

    def chown(self, uid: int, gid: int) -> None:
        with as_sftp_server():
            os.fchown(self.file.fileno(), uid, gid)

    def close(self) -> None:
        self.file.close()

    @property
    def closed(self) -> bool:
        return self.file.closed


class LocalSftp:
    def __init__(self) -> None:
        self.channel = SftpChannel()
        self.opened: list[LocalFile] = []

    def get_channel(self) -> SftpChannel:
        return self.channel

    def normalize(self, path: str) -> str:
        with as_sftp_server():
            resolved = os.path.realpath(path)
            if os.path.exists(resolved) or os.path.isdir(os.path.dirname(resolved)):
                return resolved
            raise FileNotFoundError(errno.ENOENT, "No such file", path)

    def stat(self, path: str) -> SFTPAttributes:
        with as_sftp_server():
            return attributes(os.stat(path))

    def lstat(self, path: str) -> SFTPAttributes:
        with as_sftp_server():
            return attributes(os.lstat(path))

    def listdir_attr(self, path: str) -> list[SFTPAttributes]:
        with as_sftp_server():
            return [
                attributes(os.lstat(os.path.join(path, name)), name)
                for name in os.listdir(path)
            ]

    def open(self, path: str, mode: str = "r") -> LocalFile:
        with as_sftp_server():
            if "x" in mode:
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                handle = LocalFile(os.open(path, flags, 0o666), "wb")
            else:
                handle = LocalFile(os.open(path, os.O_RDONLY), "rb")
        self.opened.append(handle)
        return handle

    def mkdir(self, path: str, mode: int = 0o777) -> None:
        with as_sftp_server():
            os.mkdir(path, mode)

    def rmdir(self, path: str) -> None:
        with as_sftp_server():
            os.rmdir(path)

    def remove(self, path: str) -> None:
        with as_sftp_server():
            os.remove(path)

    def rename(self, old: str, new: str) -> None:
        with as_sftp_server():
            if stat.S_ISREG(os.lstat(old).st_mode):
                os.link(old, new)
                os.unlink(old)
            elif os.path.exists(new):
                raise FileExistsError(errno.EEXIST, "File exists")
            else:
                os.rename(old, new)

    def posix_rename(self, old: str, new: str) -> None:
        with as_sftp_server():
            os.rename(old, new)


class LocalSftpSession:
    def __init__(self) -> None:
        self.sftp = LocalSftp()
        self.closed = False

    def close(self) -> None:
        self.closed = True
