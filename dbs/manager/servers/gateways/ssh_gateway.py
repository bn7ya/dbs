from __future__ import annotations

import base64
import json
import math
import os
import posixpath
import re
import secrets
import shlex
import stat
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from io import BytesIO
from typing import TYPE_CHECKING, BinaryIO, Protocol, cast

from django.conf import settings
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from paramiko import Channel, PKey, SFTPAttributes, SFTPClient, SFTPFile, SSHException
from paramiko.pkey import UnknownKeyType

from dbs.exceptions import ConfigurationError, ConnectionLost, DBSError, RemoteTimeout
from dbs.manager.servers import versions
from dbs.manager.servers.exceptions import (
    ArchiveFailed,
    DbsTooOld,
    FileExists,
    FileTooLarge,
    FolderNotEmpty,
    HostKeyChanged,
    RemoteCommandFailed,
    RemoteCommandTimedOut,
    RemoteNotFound,
    RemotePermissionDenied,
    RestoreFailed,
    ServerConnectionLost,
    SSHAuthFailed,
    SSHUnreachable,
    StreamBroken,
)
from dbs.naming import is_backup_name, parse_backup_moment
from dbs.tee import is_partial_name, is_stale
from dbs.transports import HostKey, HostKeyError, RemoteResult, SSHSession, SSHTarget
from dbs.transports import fetch_host_key as dbs_fetch_host_key
from dbs.transports.ssh import StreamInterrupted

if TYPE_CHECKING:
    from _typeshed import SupportsRead

ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

TRANSPORT_ERRORS = (DBSError, SSHException, OSError, EOFError)

SFTP_ERRORS = (*TRANSPORT_ERRORS, UnicodeDecodeError)

MALFORMED_KEY_ERRORS = (
    ConfigurationError,
    UnknownKeyType,
    SSHException,
    ValueError,
    OverflowError,
)

OUTPUT_TAIL = 500

TAR_OK = 0
TAR_FILES_CHANGED = 1
FILES_CHANGED = "files_changed"
SHA256SUM_LINE = re.compile(r"\\?([0-9a-f]{64}) ")
SHA256_HEX = re.compile(r"[0-9a-f]{64}")
RESTORED = re.compile(r"Restored (\d+) records and (\d+) files")
WOULD_RESTORE = re.compile(r"(\d+) records and (\d+) files would be restored")
FLUSHED = re.compile(r"Flushed (\d+) existing rows")
WOULD_FLUSH = re.compile(r"Flush would first delete (\d+) existing rows")
HEALED = "Corruption detected and repaired"
UNKNOWN_OPTION = "unrecognized arguments"
COMPOSE_PROJECT_LABEL = "com.docker.compose.project"
COMPOSE_SERVICE_LABEL = "com.docker.compose.service"
PROGRESS_OPTION = "unrecognized arguments: --progress-seconds"
RESTORE_FILE_PREFIX = ".dbs-restore-"
RESTORE_FILE_MODE = 0o600
NEW_FILE_MODE = 0o600
REMOTE_DIRECTORY_MODE = 0o700
PARTIAL_FILE_MODE = 0o600
TRANSFER_WINDOW = 4 * 1024 * 1024
NAME_MAX_BYTES = 255
PARTIAL_NAME_BYTES = NAME_MAX_BYTES - len(".") - len(".part-") - 16
DOCKER = "docker"
PODMAN = "podman"
ENGINES = (DOCKER, PODMAN)
ENGINE_VERSION_FORMATS = {DOCKER: "{{.Server.Version}}", PODMAN: "{{.Version}}"}
CONTAINER_TMP = "/tmp"
TOO_LARGE_STATUS = 3
NOT_A_FILE_STATUS = 4
LIST_FILES = (
    "import json, os, sys; folder = sys.argv[1]; "
    "entries = os.scandir(folder) if os.path.isdir(folder) else (); "
    "print(json.dumps([[entry.name, entry.stat(follow_symlinks=False).st_size, "
    "int(entry.stat(follow_symlinks=False).st_mtime)] for entry in entries "
    "if entry.is_file(follow_symlinks=False)]))"
)
READ_SMALL = """
import base64, os, stat, sys
path, limit = sys.argv[1], int(sys.argv[2])
try:
    found = os.stat(path)
except OSError:
    sys.exit(4)
if not stat.S_ISREG(found.st_mode):
    sys.exit(4)
if found.st_size > limit:
    sys.exit(3)
with open(path, "rb") as handle:
    data = handle.read(limit + 1)
if len(data) > limit:
    sys.exit(3)
sys.stdout.write(base64.b64encode(data).decode())
"""
RECEIVE_FILE = """
import os, sys
path, size = sys.argv[1], int(sys.argv[2])
mode = int(sys.argv[3], 8) if len(sys.argv) > 3 else 0o600
partial = sys.argv[4] if len(sys.argv) > 4 else ""
target = partial or path
descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
try:
    left = size
    with os.fdopen(descriptor, "wb") as handle:
        while left:
            chunk = sys.stdin.buffer.read(min(left, 1 << 20))
            if not chunk:
                break
            handle.write(chunk)
            left -= len(chunk)
        handle.flush()
        os.fsync(handle.fileno())
    if left:
        sys.exit(5)
    os.chmod(target, mode)
    if partial:
        os.replace(partial, path)
except BaseException:
    try:
        os.unlink(target)
    except OSError:
        pass
    raise
"""
MODE_OF = """
import os, stat, sys
try:
    print(oct(stat.S_IMODE(os.stat(sys.argv[1]).st_mode)))
except OSError:
    print("")
"""
SWEEP_STALE = """
import os, re, sys, time
pattern = re.compile(r"^(\\..+\\.part-[0-9a-f]{16}|\\.dbs-restore-[0-9a-f]{16}\\.dbs)$")
removed = 0
for folder in sys.argv[1:]:
    try:
        entries = list(os.scandir(folder))
    except OSError:
        continue
    for entry in entries:
        try:
            if (
                pattern.match(entry.name)
                and entry.is_file(follow_symlinks=False)
                and time.time() - entry.stat(follow_symlinks=False).st_mtime > 3600
            ):
                os.unlink(entry.path)
                removed += 1
        except OSError:
            pass
print(removed)
"""
TIMEOUT = "timeout"
TIMEOUT_PROBE = (TIMEOUT, "-k", "1", "5", "true")
TIMED_OUT_STATUSES = frozenset({124, 128 + 9})
DEADLINE_MARGIN = 5


@dataclass(frozen=True)
class Credentials:
    host: str
    port: int
    username: str
    host_key: str
    private_key: str | None = field(default=None, repr=False)
    key_passphrase: str | None = field(default=None, repr=False)
    password: str | None = field(default=None, repr=False)
    remote_dir: str = "."
    timeout_on_host: bool = False
    timeout_in_container: bool = False
    on_activity: Callable[[int], None] | None = field(
        default=None, repr=False, compare=False
    )


@dataclass(frozen=True)
class ContainerTarget:
    engine: str = DOCKER
    service: str = ""
    files: tuple[str, ...] = ()
    project: str = ""
    container: str = ""
    workdir: str = ""

    @property
    def in_compose(self) -> bool:
        return bool(self.service)

    @property
    def name(self) -> str:
        return self.service or self.container

    def argv(self, *arguments: str) -> list[str]:
        files = [part for path in self.files for part in ("-f", path)]
        project = ["-p", self.project] if self.project else []
        return [self.engine, "compose", *files, *project, *arguments]

    def exec_argv(
        self,
        command: Sequence[str],
        *,
        settings_module: str | None = None,
        user: str | None = None,
        stdin: bool = False,
    ) -> list[str]:
        options = ["-T"] if self.in_compose else (["-i"] if stdin else [])
        options += ["-u", user] if user else []
        options += ["-w", self.workdir] if self.workdir else []
        options += (
            ["-e", f"DJANGO_SETTINGS_MODULE={settings_module}"]
            if settings_module
            else []
        )
        if self.in_compose:
            return self.argv("exec", *options, self.service, *command)
        return [self.engine, "exec", *options, self.container, *command]

    def version_argv(self) -> list[str]:
        if self.in_compose:
            return [self.engine, "compose", "version", "--short"]
        return [self.engine, "version", "--format", ENGINE_VERSION_FORMATS[self.engine]]

    def running_argv(self) -> list[str]:
        if not self.in_compose:
            return [self.engine, "inspect", "--format", "{{.State.Running}}", self.container]
        project = (
            ["--filter", f"label={COMPOSE_PROJECT_LABEL}={self.project}"]
            if self.project
            else []
        )
        return [
            self.engine,
            "ps",
            *project,
            "--filter",
            f"label={COMPOSE_SERVICE_LABEL}={self.service}",
            "--filter",
            "status=running",
            "--format",
            "{{.Names}}",
        ]

    def running_in(self, output: str) -> bool:
        if self.in_compose:
            return bool(output.strip())
        return output.strip().splitlines()[-1:] == ["true"]


@dataclass(frozen=True)
class DbsProfile:
    python: str
    manage: str
    project_dir: str | None = None
    settings_module: str | None = None
    container: ContainerTarget | None = None


@dataclass(frozen=True)
class ServerBackup:
    name: str
    path: str
    size: int
    mtime: datetime | None


@dataclass(frozen=True)
class StreamedBackup:
    name: str
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class RestoreReport:
    records: int | None
    files: int | None
    flushed: int | None
    healed: bool
    copy_left: str = ""


@dataclass(frozen=True)
class RemoteArchive:
    remote_path: str
    sha256: str
    warning: str


@dataclass(frozen=True)
class RemoteFile:
    name: str
    path: str
    size: int | None
    mtime: datetime | None


class EntryKind:
    FILE = "file"
    FOLDER = "folder"
    LINK = "link"
    OTHER = "other"
    ALL = (FILE, FOLDER, LINK, OTHER)


@dataclass(frozen=True)
class RemoteEntry:
    name: str
    path: str
    kind: EntryKind
    size: int | None
    mtime: datetime | None
    permissions: int | None
    uid: int | None = None
    gid: int | None = None


class Writable(Protocol):
    def write(self, data: bytes) -> object: ...


class RemoteReader:
    def __init__(self, handle: SFTPFile) -> None:
        self._handle: SFTPFile = handle

    def read(self, size: int = -1) -> bytes:
        try:
            return self._handle.read(size)
        except TRANSPORT_ERRORS as exc:
            raise RemoteCommandFailed() from exc


class RemoteHost:
    def __init__(
        self,
        session: SSHSession,
        *,
        timeout_on_host: bool = False,
        timeout_in_container: bool = False,
    ) -> None:
        self.session = session
        self.timeout_on_host = timeout_on_host
        self.timeout_in_container = timeout_in_container

    @property
    def sftp(self) -> SFTPClient:
        try:
            sftp: SFTPClient = self.session.sftp
            cast(Channel, sftp.get_channel()).settimeout(settings.SSH_IO_TIMEOUT)
        except TRANSPORT_ERRORS as exc:
            raise RemoteCommandFailed() from exc
        return sftp

    def exists(self, path: str) -> bool:
        sftp = self.sftp
        try:
            sftp.stat(path)
        except OSError:
            return False
        except (SSHException, EOFError) as exc:
            raise RemoteCommandFailed() from exc
        return True

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        stdin_line: str | None = None,
        timeout: float | None = None,
        limited: bool = False,
    ) -> RemoteResult:
        seconds = timeout or settings.SSH_COMMAND_TIMEOUT
        if self.timeout_on_host and not limited:
            argv, limited = bounded(argv, seconds), True
        script = build_script(argv, cwd=cwd, env=env)
        settles_at = timezone.now() + timedelta(
            seconds=seconds + settings.REMOTE_KILL_AFTER
        )
        try:
            result = self.session.run(
                script, stdin_line=stdin_line, timeout=_waited(seconds, limited)
            )
        except TRANSPORT_ERRORS as exc:
            raise _interrupted(exc, settles_at) from exc
        if limited and result.exit_status in TIMED_OUT_STATUSES:
            raise RemoteCommandTimedOut(output=_tail(result.stderr or result.stdout))
        return result

    def has_timeout(self, profile: DbsProfile | None = None) -> bool:
        if profile is None or profile.container is None:
            probe = list(TIMEOUT_PROBE)
            cwd = None
        else:
            probe = profile.container.exec_argv(TIMEOUT_PROBE)
            cwd = profile.project_dir
        return bool(self.run(probe, cwd=cwd, limited=True).ok)

    def run_python(
        self,
        profile: DbsProfile,
        arguments: Sequence[str],
        *,
        python: str | None = None,
        stdin_line: str | None = None,
        timeout: float | None = None,
        with_settings: bool = True,
    ) -> RemoteResult:
        command = [python or profile.python, *arguments]
        settings_module = profile.settings_module if with_settings else None
        if profile.container is None:
            return self.run(
                command,
                cwd=profile.project_dir,
                env={"DJANGO_SETTINGS_MODULE": settings_module}
                if settings_module
                else None,
                stdin_line=stdin_line,
                timeout=timeout,
            )
        seconds = timeout or settings.SSH_COMMAND_TIMEOUT
        inside = self.timeout_in_container
        return self.run(
            profile.container.exec_argv(
                bounded(command, seconds) if inside else command,
                settings_module=settings_module,
                stdin=stdin_line is not None,
            ),
            cwd=profile.project_dir,
            stdin_line=stdin_line,
            timeout=seconds,
            limited=inside,
        )

    def run_manage(
        self,
        profile: DbsProfile,
        arguments: Sequence[str],
        *,
        stdin_line: str | None = None,
        timeout: float | None = None,
    ) -> RemoteResult:
        return self.run_python(
            profile,
            [profile.manage, *arguments],
            stdin_line=stdin_line,
            timeout=timeout,
        )

    def run_compose(
        self,
        profile: DbsProfile,
        arguments: Sequence[str],
        *,
        timeout: float | None = None,
    ) -> RemoteResult:
        if profile.container is None or not profile.container.in_compose:
            raise ValueError("This application does not run in a Compose service.")
        return self.run(
            profile.container.argv(*arguments), cwd=profile.project_dir, timeout=timeout
        )

    def run_engine(
        self,
        profile: DbsProfile,
        argv: Sequence[str],
        *,
        timeout: float | None = None,
    ) -> RemoteResult:
        if profile.container is None:
            raise ValueError("This application does not run in a container.")
        return self.run(argv, cwd=profile.project_dir, timeout=timeout)

    def run_in_container(
        self,
        profile: DbsProfile,
        command: Sequence[str],
        *,
        user: str | None = None,
        timeout: float | None = None,
    ) -> RemoteResult:
        if profile.container is None:
            raise ValueError("This application does not run in a container.")
        seconds = timeout or settings.SSH_COMMAND_TIMEOUT
        inside = self.timeout_in_container
        return self.run(
            profile.container.exec_argv(
                bounded(command, seconds) if inside else command, user=user
            ),
            cwd=profile.project_dir,
            timeout=seconds,
            limited=inside,
        )

    def stream(
        self,
        argv: Sequence[str],
        sink: Writable,
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        stdin_line: str | None = None,
        timeout: float | None = None,
        progress: Callable[[int], None] | None = None,
        limited: bool = False,
        idle_timeout: float | None = None,
        on_stderr_line: Callable[[str], None] | None = None,
    ) -> RemoteResult:
        seconds = timeout or settings.BACKUP_EXEC_TIMEOUT
        if self.timeout_on_host and not limited:
            argv, limited = bounded(argv, seconds), True
        script = build_script(argv, cwd=cwd, env=env)
        secret = stdin_line or ""
        try:
            result = self.session.stream(
                script,
                sink,
                stdin_line=stdin_line,
                timeout=_waited(seconds, limited),
                progress=progress,
                idle_timeout=idle_timeout,
                on_stderr_line=on_stderr_line,
            )
        except StreamInterrupted as exc:
            raise StreamBroken(output=_tail(str(exc), secret)) from exc
        except DBSError as exc:
            raise RemoteCommandFailed(output=_tail(str(exc), secret)) from exc
        if limited and result.exit_status in TIMED_OUT_STATUSES:
            raise RemoteCommandTimedOut(output=_tail(result.stderr, secret))
        return result

    def backup_folder(self, profile: DbsProfile, folder: str) -> str:
        if profile.container is None:
            return folder
        found = self.run_manage(profile, ["dbs_connection", "--json"])
        details = _json_of(found.stdout) if found.ok else None
        if not isinstance(details, dict):
            raise RemoteCommandFailed(output=_tail(found.stderr or found.stdout))
        chosen = details.get("remote_backup_dir")
        return chosen if isinstance(chosen, str) else ""

    def waiting_backups(
        self, profile: DbsProfile, folder: str, prefix: str
    ) -> list[ServerBackup]:
        if not folder:
            return []
        found = [
            backup
            for backup in self.folder_files(profile, folder)
            if is_backup_name(backup.name, prefix)
        ]
        return sorted(
            found, key=lambda backup: (parse_backup_moment(backup.name), backup.name)
        )

    def folder_files(self, profile: DbsProfile, folder: str) -> list[ServerBackup]:
        listed = (
            self._listed_on_host(folder)
            if profile.container is None
            else self._listed_in_container(profile, folder)
        )
        return [
            ServerBackup(name, posixpath.join(folder, name), size, mtime)
            for name, size, mtime in listed
        ]

    def backup_sha256(self, profile: DbsProfile, path: str) -> str:
        if profile.container is None:
            return self._sha256(path, settings.BACKUP_EXEC_TIMEOUT)
        result = self.run_in_container(
            profile, ["sha256sum", "--", path], timeout=settings.BACKUP_EXEC_TIMEOUT
        )
        return _digest_in(result)

    def pull_backup(
        self,
        profile: DbsProfile,
        path: str,
        sink: Writable,
        progress: Callable[[int], None] | None = None,
        *,
        offset: int = 0,
    ) -> None:
        if offset < 0:
            raise ValueError(f"Not an offset: {offset!r}")
        if profile.container is None:
            received = offset
            with self.stream_file(path, start=offset) as chunks:
                for chunk in chunks:
                    sink.write(chunk)
                    received += len(chunk)
                    if progress is not None:
                        progress(received)
            return
        seconds = settings.BACKUP_TOTAL_TIMEOUT
        inside = self.timeout_in_container
        command = ["tail", "-c", f"+{offset + 1}", "--", path] if offset else ["cat", "--", path]
        try:
            result = self.stream(
                profile.container.exec_argv(
                    bounded(command, seconds) if inside else command
                ),
                sink,
                cwd=profile.project_dir,
                timeout=seconds,
                progress=progress,
                limited=inside,
                idle_timeout=settings.BACKUP_IDLE_TIMEOUT,
            )
        except StreamBroken as exc:
            raise RemoteCommandFailed(output=exc.output) from exc
        if not result.ok:
            raise RemoteCommandFailed(output=_tail(result.stderr))

    @sensitive_variables("passphrase")
    def stream_dbs_backup(
        self,
        profile: DbsProfile,
        *,
        passphrase: str,
        prefix: str,
        folder: str,
        sink: Writable,
        progress: Callable[[int], None] | None = None,
        progress_seconds: int = 0,
        on_started: Callable[[dict[str, str]], None] | None = None,
    ) -> StreamedBackup:
        arguments = ["dbs_backup", "--stream", "--prefix", prefix, "--passphrase-stdin"]
        arguments += ["--output-dir", folder] if folder else []
        arguments += ["--progress-seconds", str(progress_seconds)] if progress_seconds else []
        command = [profile.python, profile.manage, *arguments]
        seconds = settings.BACKUP_TOTAL_TIMEOUT
        idle = (
            settings.BACKUP_IDLE_TIMEOUT
            if progress_seconds
            else settings.BACKUP_QUIET_TIMEOUT
        )
        inside = profile.container is not None and self.timeout_in_container
        if profile.container is None:
            argv = command
            env = (
                {"DJANGO_SETTINGS_MODULE": profile.settings_module}
                if profile.settings_module
                else None
            )
        else:
            argv = profile.container.exec_argv(
                bounded(command, seconds) if inside else command,
                settings_module=profile.settings_module,
                stdin=True,
            )
            env = None
        result = self.stream(
            argv,
            sink,
            cwd=profile.project_dir,
            env=env,
            stdin_line=passphrase,
            timeout=seconds,
            progress=progress,
            limited=inside,
            idle_timeout=idle,
            on_stderr_line=None if on_started is None else _started(prefix, on_started),
        )
        output = _tail(result.stderr, passphrase)
        if not result.ok:
            if progress_seconds and PROGRESS_OPTION in result.stderr:
                return self.stream_dbs_backup(
                    profile,
                    passphrase=passphrase,
                    prefix=prefix,
                    folder=folder,
                    sink=sink,
                    progress=progress,
                )
            if UNKNOWN_OPTION in result.stderr:
                raise DbsTooOld(versions.MINIMUM_REMOTE, output=output)
            raise RemoteCommandFailed(output=output)
        summary = _stream_summary(result.stderr, prefix)
        if summary is None:
            raise RemoteCommandFailed(output=output)
        if summary.get("kept_on_server") is True:
            raise StreamBroken(output=output)
        name = summary["name"]
        return StreamedBackup(
            name=name,
            path=posixpath.join(folder, name) if folder else "",
            size=summary["size"],
            sha256=summary["sha256"],
        )

    def remove_backup(self, profile: DbsProfile, path: str) -> None:
        if profile.container is None:
            self.remove(path)
            return
        result = self.run_in_container(profile, ["rm", "-f", "--", path])
        if not result.ok:
            raise RemoteCommandFailed(output=_tail(result.stderr or result.stdout))

    def sweep_partials(self, folder: str) -> list[str]:
        try:
            entries = self.sftp.listdir_attr(folder)
        except (RemoteCommandFailed, *SFTP_ERRORS):
            return []
        removed = []
        for entry in entries:
            if (
                is_partial_name(entry.filename)
                and _is_file(entry.st_mode)
                and entry.st_mtime is not None
                and is_stale(entry.st_mtime)
            ):
                with suppress(RemoteCommandFailed):
                    self.remove(posixpath.join(folder, entry.filename))
                    removed.append(entry.filename)
        return sorted(removed)

    def _listed_on_host(self, folder: str) -> list[tuple[str, int, datetime | None]]:
        try:
            listed = self.list_files(folder)
        except RemoteNotFound:
            return []
        return [(file.name, file.size or 0, file.mtime) for file in listed]

    def _listed_in_container(
        self, profile: DbsProfile, folder: str
    ) -> list[tuple[str, int, datetime | None]]:
        result = self.run_python(
            profile, ["-c", LIST_FILES, folder], with_settings=False
        )
        rows = _json_of(result.stdout) if result.ok else None
        if not isinstance(rows, list):
            raise RemoteCommandFailed(output=_tail(result.stderr or result.stdout))
        return [
            (row[0], row[1], _listed_time(row[2])) for row in rows if _is_listed(row)
        ]

    def _remove_in_container(self, profile: DbsProfile, path: str) -> str:
        try:
            removed = self.run_in_container(profile, ["rm", "-f", "--", path])
        except RemoteCommandFailed:
            return path
        return "" if removed.ok else path

    @sensitive_variables("passphrase")
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
        name = f"{RESTORE_FILE_PREFIX}{secrets.token_hex(8)}.dbs"
        if profile.container is None:
            path = posixpath.join(remote_dir, name)
            self._make_dirs(remote_dir)
            self.write_new(source, remote_dir, name, mode=RESTORE_FILE_MODE)
        else:
            path = posixpath.join(CONTAINER_TMP, name)
            self._receive_in_container(profile, source, path)
        arguments = ["dbs_restore", path, "--passphrase-stdin"]
        arguments += ["--flush"] if flush else []
        arguments += ["--dry-run"] if dry_run else []
        try:
            result = self.run_manage(
                profile,
                arguments,
                stdin_line=passphrase,
                timeout=settings.BACKUP_EXEC_TIMEOUT,
            )
        finally:
            copy_left = (
                self._removed_or_left(path)
                if profile.container is None
                else self._remove_in_container(profile, path)
            )
        if not result.ok:
            output = _tail(f"{result.stdout}\n{result.stderr}", passphrase)
            if UNKNOWN_OPTION in result.stderr:
                raise DbsTooOld(versions.MINIMUM_REMOTE, output=output)
            raise RestoreFailed(output=output)
        return _restore_report(
            result.stdout, flush=flush, dry_run=dry_run, copy_left=copy_left
        )

    def _receive_in_container(
        self, profile: DbsProfile, source: BinaryIO, path: str
    ) -> None:
        received = self.feed_python(
            profile,
            ["-c", RECEIVE_FILE, path, str(_remaining(source))],
            source,
            timeout=settings.BACKUP_EXEC_TIMEOUT,
        )
        if not received.ok:
            raise RestoreFailed(output=_tail(received.stderr or received.stdout))

    def read_in_container(self, profile: DbsProfile, path: str, max_bytes: int) -> bytes:
        result = self.run_python(
            profile, ["-c", READ_SMALL, path, str(max_bytes)], with_settings=False
        )
        if result.exit_status == TOO_LARGE_STATUS:
            raise FileTooLarge()
        if result.exit_status == NOT_A_FILE_STATUS:
            raise RemoteNotFound()
        if not result.ok:
            raise RemoteCommandFailed(output=_tail(result.stderr))
        try:
            return base64.b64decode(result.stdout.strip(), validate=True)
        except ValueError as exc:
            raise RemoteCommandFailed() from exc

    @sensitive_variables("data")
    def replace_in_container(self, profile: DbsProfile, path: str, data: bytes) -> None:
        folder, name = posixpath.split(path)
        if not folder.startswith("/") or name in {"", ".", ".."}:
            raise ValueError(f"Not an absolute file path: {path!r}")
        current = self.run_python(
            profile, ["-c", MODE_OF, path], with_settings=False
        )
        mode = current.stdout.strip() if current.ok else ""
        written = self.feed_python(
            profile,
            [
                "-c",
                RECEIVE_FILE,
                path,
                str(len(data)),
                mode or oct(NEW_FILE_MODE),
                posixpath.join(folder, _partial_name(name)),
            ],
            BytesIO(data),
        )
        if not written.ok:
            raise RemoteCommandFailed(output=_tail(written.stderr or written.stdout))

    def sweep_in_container(self, profile: DbsProfile, *folders: str) -> int:
        try:
            result = self.run_python(
                profile, ["-c", SWEEP_STALE, *folders], with_settings=False
            )
        except RemoteCommandFailed:
            return 0
        lines = result.stdout.strip().splitlines() if result.ok else []
        return int(lines[-1]) if lines and lines[-1].isdigit() else 0

    def feed_python(
        self,
        profile: DbsProfile,
        arguments: Sequence[str],
        source: BinaryIO,
        *,
        timeout: float | None = None,
    ) -> RemoteResult:
        if profile.container is None:
            raise ValueError("This application does not run in a container.")
        seconds = timeout or settings.SSH_COMMAND_TIMEOUT
        inside = self.timeout_in_container
        command = [profile.python, *arguments]
        return self.feed(
            profile.container.exec_argv(
                bounded(command, seconds) if inside else command, stdin=True
            ),
            source,
            cwd=profile.project_dir,
            timeout=seconds,
            limited=inside,
        )

    def feed(
        self,
        argv: Sequence[str],
        source: BinaryIO,
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
        limited: bool = False,
    ) -> RemoteResult:
        seconds = timeout or settings.SSH_COMMAND_TIMEOUT
        if self.timeout_on_host and not limited:
            argv, limited = bounded(argv, seconds), True
        script = build_script(argv, cwd=cwd, env=env)
        try:
            result = self.session.feed(
                script, source, timeout=_waited(seconds, limited)
            )
        except DBSError as exc:
            raise RemoteCommandFailed(output=_tail(str(exc))) from exc
        if limited and result.exit_status in TIMED_OUT_STATUSES:
            raise RemoteCommandTimedOut(output=_tail(result.stderr))
        return result

    def archive(
        self, paths: Sequence[str], remote_dir: str, name: str, timeout: float
    ) -> RemoteArchive:
        if not paths:
            raise ValueError("Nothing to archive.")
        if "/" in name or name in {"", ".", ".."}:
            raise ValueError(f"Not a file name: {name!r}")
        self._make_dirs(remote_dir)
        remote_path = posixpath.join(remote_dir, name)
        members = [path.lstrip("/") or "." for path in paths]
        made = self.run(
            ["tar", "-czf", remote_path, "-C", "/", "--", *members], timeout=timeout
        )
        if made.exit_status not in (TAR_OK, TAR_FILES_CHANGED):
            with suppress(RemoteCommandFailed):
                self.remove(remote_path)
            raise ArchiveFailed(output=_tail(made.stderr or made.stdout))
        return RemoteArchive(
            remote_path=remote_path,
            sha256=self._sha256(remote_path, timeout),
            warning=FILES_CHANGED if made.exit_status == TAR_FILES_CHANGED else "",
        )

    @contextmanager
    def open_file(self, path: str) -> Iterator[RemoteReader]:
        sftp = self.sftp
        try:
            handle = sftp.open(path, "rb")
        except TRANSPORT_ERRORS as exc:
            raise RemoteCommandFailed(output=_tail(f"{path}: {exc}")) from exc
        try:
            try:
                handle.prefetch()
            except TRANSPORT_ERRORS as exc:
                raise RemoteCommandFailed() from exc
            yield RemoteReader(handle)
        finally:
            with suppress(*TRANSPORT_ERRORS):
                handle.close()

    def list_files(self, folder: str) -> list[RemoteFile]:
        sftp = self.sftp
        try:
            entries = sftp.listdir_attr(folder)
        except SFTP_ERRORS as exc:
            raise _translated(exc, folder) from exc
        files = (
            RemoteFile(
                name=entry.filename,
                path=posixpath.join(folder, entry.filename),
                size=entry.st_size,
                mtime=_listed_time(entry.st_mtime),
            )
            for entry in entries
            if entry.st_mode is not None and stat.S_ISREG(entry.st_mode)
        )
        return sorted(files, key=lambda file: file.name)

    def home_folder(self, name: str) -> str:
        return posixpath.join(self.realpath("."), name)

    def realpath(self, path: str) -> str:
        sftp = self.sftp
        try:
            return sftp.normalize(path)
        except SFTP_ERRORS as exc:
            raise _translated(exc, path) from exc

    def lstat(self, path: str) -> RemoteEntry:
        sftp = self.sftp
        try:
            attributes = sftp.lstat(path)
        except SFTP_ERRORS as exc:
            raise _translated(exc, path) from exc
        return _entry(posixpath.basename(path), path, attributes)

    def listdir(self, folder: str) -> list[RemoteEntry]:
        sftp = self.sftp
        try:
            entries = sftp.listdir_attr(folder)
        except SFTP_ERRORS as exc:
            raise _translated(exc, folder) from exc
        return [
            _entry(entry.filename, posixpath.join(folder, entry.filename), entry)
            for entry in entries
        ]

    def listdir_limited(
        self, folder: str, limit: int
    ) -> tuple[list[RemoteEntry], bool]:
        sftp = self.sftp
        kept: list[RemoteEntry] = []
        truncated = False
        try:
            for entry in sftp.listdir_iter(folder):
                if len(kept) < limit:
                    path = posixpath.join(folder, entry.filename)
                    kept.append(_entry(entry.filename, path, entry))
                else:
                    truncated = True
        except SFTP_ERRORS as exc:
            raise _translated(exc, folder) from exc
        return kept, truncated

    @contextmanager
    def stream_file(
        self, path: str, limit: int | None = None, *, start: int = 0
    ) -> Iterator[Iterator[bytes]]:
        sftp = self.sftp
        try:
            handle = sftp.open(path, "rb")
        except SFTP_ERRORS as exc:
            raise _translated(exc, path) from exc
        try:
            yield _windows(handle, limit, start)
        finally:
            with suppress(*TRANSPORT_ERRORS):
                handle.close()

    def write_new(
        self,
        source: SupportsRead[bytes],
        folder: str,
        name: str,
        *,
        mode: int | None = None,
    ) -> RemoteEntry:
        if "/" in name or name in {"", ".", ".."}:
            raise ValueError(f"Not a file name: {name!r}")
        sftp = self.sftp
        target = posixpath.join(folder, name)
        if self._lexists(target):
            raise FileExists()
        partial = posixpath.join(folder, _partial_name(name))
        try:
            handle = sftp.open(partial, "wx")
        except SFTP_ERRORS as exc:
            raise _translated(exc, folder) from exc
        try:
            with _closing(handle):
                _write_whole(handle, source, partial, mode=mode)
            if self._lexists(target):
                raise FileExists()
            try:
                sftp.rename(partial, target)
            except SFTP_ERRORS as exc:
                if _sftp_failure(exc) and self._lexists(target):
                    raise FileExists() from exc
                raise _translated(exc, target) from exc
        except BaseException:
            with suppress(*TRANSPORT_ERRORS):
                sftp.remove(partial)
            raise
        return self.lstat(target)

    @sensitive_variables()
    def read_small(self, path: str, max_bytes: int) -> bytes:
        sftp = self.sftp
        try:
            attributes = sftp.stat(path)
        except SFTP_ERRORS as exc:
            raise _translated(exc, path) from exc
        if attributes.st_mode is not None and not stat.S_ISREG(attributes.st_mode):
            raise RemoteNotFound()
        if attributes.st_size is not None and attributes.st_size > max_bytes:
            raise FileTooLarge()
        try:
            handle = sftp.open(path, "rb")
        except SFTP_ERRORS as exc:
            raise _translated(exc, path) from exc
        with _closing(handle):
            try:
                data = handle.read(max_bytes + 1)
            except SFTP_ERRORS as exc:
                raise _translated(exc, path) from exc
        if len(data) > max_bytes:
            raise FileTooLarge()
        return data

    @sensitive_variables()
    def replace_file(
        self, path: str, data: bytes, *, mode: int, owner: tuple[int, int] | None = None
    ) -> RemoteEntry:
        folder, name = posixpath.split(path)
        if not folder.startswith("/") or name in {"", ".", ".."}:
            raise ValueError(f"Not an absolute file path: {path!r}")
        sftp = self.sftp
        partial = posixpath.join(folder, _partial_name(name))
        try:
            handle = sftp.open(partial, "wx")
        except SFTP_ERRORS as exc:
            raise _translated(exc, folder) from exc
        try:
            with _closing(handle):
                _write_whole(handle, BytesIO(data), partial, mode=mode, owner=owner)
            try:
                sftp.posix_rename(partial, path)
            except SFTP_ERRORS as exc:
                raise _translated(exc, path) from exc
        except BaseException:
            with suppress(*TRANSPORT_ERRORS):
                sftp.remove(partial)
            raise
        return self.lstat(path)

    def make_folder(self, path: str) -> RemoteEntry:
        sftp = self.sftp
        try:
            sftp.mkdir(path)
        except SFTP_ERRORS as exc:
            if _sftp_failure(exc) and self._lexists(path):
                raise FileExists() from exc
            raise _translated(exc, path) from exc
        return self.lstat(path)

    def remove_file(self, path: str) -> None:
        sftp = self.sftp
        try:
            sftp.remove(path)
        except SFTP_ERRORS as exc:
            raise _translated(exc, path) from exc

    def remove_empty_folder(self, path: str) -> None:
        sftp = self.sftp
        try:
            sftp.rmdir(path)
        except SFTP_ERRORS as exc:
            if _sftp_failure(exc) and self._holds_anything(path):
                raise FolderNotEmpty() from exc
            raise _translated(exc, path) from exc

    def remove(self, path: str) -> None:
        sftp = self.sftp
        try:
            sftp.remove(path)
        except FileNotFoundError:
            return
        except TRANSPORT_ERRORS as exc:
            raise RemoteCommandFailed(output=_tail(f"{path}: {exc}")) from exc

    def prune(self, remote_dir: str, pattern: re.Pattern[str], keep: int) -> None:
        sftp = self.sftp
        try:
            entries = sftp.listdir_attr(remote_dir)
        except FileNotFoundError:
            return
        except TRANSPORT_ERRORS as exc:
            raise RemoteCommandFailed(output=_tail(f"{remote_dir}: {exc}")) from exc
        matching = sorted(
            (
                entry
                for entry in entries
                if pattern.fullmatch(entry.filename) and _is_file(entry.st_mode)
            ),
            key=lambda entry: (entry.st_mtime or 0, entry.filename),
        )
        for entry in matching[: max(len(matching) - keep, 0)]:
            self.remove(posixpath.join(remote_dir, entry.filename))

    def _removed_or_left(self, path: str) -> str:
        try:
            self.remove(path)
        except RemoteCommandFailed:
            return path
        return ""

    def _lexists(self, path: str) -> bool:
        try:
            self.sftp.lstat(path)
        except FileNotFoundError:
            return False
        except SFTP_ERRORS as exc:
            raise _translated(exc, path) from exc
        return True

    def _holds_anything(self, folder: str) -> bool:
        try:
            return bool(self.sftp.listdir_attr(folder))
        except SFTP_ERRORS as exc:
            raise _translated(exc, folder) from exc

    def _make_dirs(self, path: str) -> None:
        sftp = self.sftp
        current = "/" if path.startswith("/") else ""
        for part in (part for part in path.split("/") if part):
            current = posixpath.join(current, part) if current else part
            try:
                try:
                    sftp.stat(current)
                except FileNotFoundError:
                    sftp.mkdir(current, mode=REMOTE_DIRECTORY_MODE)
            except TRANSPORT_ERRORS as exc:
                raise RemoteCommandFailed(output=_tail(f"{current}: {exc}")) from exc

    def _sha256(self, path: str, timeout: float) -> str:
        return _digest_in(self.run(["sha256sum", "--", path], timeout=timeout))


def _digest_in(result: RemoteResult) -> str:
    found = SHA256SUM_LINE.match(result.stdout) if result.ok else None
    if found is None:
        raise RemoteCommandFailed(output=_tail(result.stderr or result.stdout))
    return found.group(1)


def _json_of(text: str) -> object:
    try:
        return json.loads(text.strip() or "null")
    except ValueError:
        return None


def _is_listed(row: object) -> bool:
    return (
        isinstance(row, list)
        and len(row) == 3
        and isinstance(row[0], str)
        and "/" not in row[0]
        and all(isinstance(value, int) and not isinstance(value, bool) for value in row[1:])
    )


def _started(
    prefix: str, on_started: Callable[[dict[str, str]], None]
) -> Callable[[str], None]:
    told = []

    def heard(line: str) -> None:
        if told:
            return
        found = _json_of(line)
        reported = found.get("progress") if isinstance(found, dict) else None
        if not isinstance(reported, dict):
            return
        name, partial = reported.get("name"), reported.get("partial")
        if not (
            isinstance(name, str)
            and isinstance(partial, str)
            and "/" not in name
            and "/" not in partial
            and is_backup_name(name, prefix)
            and is_partial_name(partial)
        ):
            return
        told.append(name)
        on_started({"name": name, "partial": partial})

    return heard


def _stream_summary(stderr: str, prefix: str) -> dict | None:
    for line in reversed(stderr.splitlines()):
        summary = _json_of(line) if line.lstrip().startswith("{") else None
        if isinstance(summary, dict) and "progress" not in summary:
            return summary if _is_summary(summary, prefix) else None
    return None


def _is_summary(summary: dict, prefix: str) -> bool:
    name, size, digest = summary.get("name"), summary.get("size"), summary.get("sha256")
    return (
        isinstance(name, str)
        and "/" not in name
        and is_backup_name(name, prefix)
        and isinstance(size, int)
        and not isinstance(size, bool)
        and size >= 0
        and isinstance(digest, str)
        and SHA256_HEX.fullmatch(digest) is not None
    )


def _restore_report(
    stdout: str, *, flush: bool, dry_run: bool, copy_left: str
) -> RestoreReport:
    loaded = (WOULD_RESTORE if dry_run else RESTORED).search(stdout)
    flushed = (WOULD_FLUSH if dry_run else FLUSHED).search(stdout) if flush else None
    nothing_flushed = 0 if flush and dry_run and loaded else None
    return RestoreReport(
        records=int(loaded.group(1)) if loaded else None,
        files=int(loaded.group(2)) if loaded else None,
        flushed=int(flushed.group(1)) if flushed else nothing_flushed,
        healed=HEALED in stdout,
        copy_left=copy_left,
    )


def _translated(exc: BaseException, path: str) -> Exception:
    if isinstance(exc, FileNotFoundError):
        return RemoteNotFound()
    if isinstance(exc, PermissionError):
        return RemotePermissionDenied()
    return RemoteCommandFailed(output=_tail(f"{path}: {exc}"))


def _sftp_failure(exc: BaseException) -> bool:
    return type(exc) is OSError and exc.errno is None


def _entry(name: str, path: str, attributes: SFTPAttributes) -> RemoteEntry:
    mode = attributes.st_mode
    kind = _kind(mode)
    return RemoteEntry(
        name=name,
        path=path,
        kind=kind,
        size=attributes.st_size if kind == EntryKind.FILE else None,
        mtime=_listed_time(attributes.st_mtime),
        permissions=None if mode is None else stat.S_IMODE(mode),
        uid=attributes.st_uid,
        gid=attributes.st_gid,
    )


def _kind(mode: int | None) -> EntryKind:
    if mode is None:
        return EntryKind.OTHER
    if stat.S_ISLNK(mode):
        return EntryKind.LINK
    if stat.S_ISDIR(mode):
        return EntryKind.FOLDER
    if stat.S_ISREG(mode):
        return EntryKind.FILE
    return EntryKind.OTHER


def _remaining(source: BinaryIO) -> int:
    position = source.tell()
    end = source.seek(0, os.SEEK_END)
    source.seek(position)
    return end - position


def _partial_name(name: str) -> str:
    kept = name.encode()[:PARTIAL_NAME_BYTES].decode(errors="ignore")
    return f".{kept}.part-{secrets.token_hex(8)}"


def _windows(handle: SFTPFile, limit: int | None, start: int = 0) -> Iterator[bytes]:
    offset = start
    while limit is None or offset < limit:
        size = (
            TRANSFER_WINDOW if limit is None else min(TRANSFER_WINDOW, limit - offset)
        )
        try:
            chunk = b"".join(handle.readv([(offset, size)]))
        except TRANSPORT_ERRORS as exc:
            raise RemoteCommandFailed() from exc
        if not chunk:
            return
        yield chunk
        offset += len(chunk)


@sensitive_variables()
def _write_whole(
    handle: SFTPFile,
    source: SupportsRead[bytes],
    path: str,
    *,
    mode: int | None = None,
    owner: tuple[int, int] | None = None,
) -> None:
    try:
        created = handle.stat()
        handle.chmod(PARTIAL_FILE_MODE)
        handle.set_pipelined(True)
        written = 0
        while chunk := source.read(TRANSFER_WINDOW):
            handle.write(chunk)
            written += len(chunk)
        handle.flush()
        kept = handle.stat().st_size
        if kept != written:
            raise RemoteCommandFailed(
                output=f"{path}: the server kept {kept} of {written} bytes"
            )
        if owner is not None and (created.st_uid, created.st_gid) != owner:
            handle.chown(*owner)
        if mode is None and created.st_mode is not None:
            mode = created.st_mode
        if mode is not None:
            handle.chmod(stat.S_IMODE(mode))
    except SFTP_ERRORS as exc:
        raise _translated(exc, path) from exc


@contextmanager
def _closing(handle: SFTPFile) -> Iterator[None]:
    try:
        yield
    finally:
        with suppress(*TRANSPORT_ERRORS):
            handle.close()


def _listed_time(seconds: int | None) -> datetime | None:
    return None if seconds is None else datetime.fromtimestamp(seconds, dt_timezone.utc)


def _is_file(mode: int | None) -> bool:
    return mode is None or stat.S_ISREG(mode)


def _tail(output: str, secret: str = "") -> str:
    if secret:
        output = output.replace(secret, "[passphrase]")
    return output.strip()[-OUTPUT_TAIL:]


def build_script(
    argv: Sequence[str],
    *,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    lines = []
    if cwd:
        lines.append(f"cd {shlex.quote(cwd)} || exit 1")
    for name, value in sorted((env or {}).items()):
        if not ENV_NAME.match(name):
            raise ValueError(f"Not an environment variable name: {name!r}")
        lines.append(f"export {name}={shlex.quote(value)}")
    lines.append("exec " + shlex.join(argv))
    return "/bin/sh -c " + shlex.quote("\n".join(lines))


def parse_host_key(line: str) -> HostKey:
    try:
        key = HostKey.from_line(line)
        PKey.from_type_string(key.key_type, base64.b64decode(key.key_base64))
    except MALFORMED_KEY_ERRORS as exc:
        raise ValueError("Not a host key a connection can pin.") from exc
    return key


def fetch_host_key(host: str, port: int) -> HostKey:
    try:
        return dbs_fetch_host_key(host, port, timeout=settings.SSH_CONNECT_TIMEOUT)
    except DBSError as exc:
        raise SSHUnreachable() from exc


@contextmanager
def connect(credentials: Credentials) -> Iterator[RemoteHost]:
    try:
        target = SSHTarget(
            host=credentials.host,
            port=credentials.port,
            username=credentials.username,
            private_key=credentials.private_key,
            key_passphrase=credentials.key_passphrase,
            password=credentials.password,
            host_key=credentials.host_key,
            remote_dir=credentials.remote_dir,
            use_agent=False,
            auto_add_host_key=False,
            connect_timeout=settings.SSH_CONNECT_TIMEOUT,
            keepalive_interval=settings.SSH_KEEPALIVE_INTERVAL,
            io_timeout=settings.SSH_IO_TIMEOUT,
        )
        session = SSHSession(target, on_activity=credentials.on_activity).__enter__()
    except HostKeyError as exc:
        raise HostKeyChanged() from exc
    except ConfigurationError as exc:
        raise SSHAuthFailed() from exc
    except DBSError as exc:
        raise SSHUnreachable() from exc
    try:
        yield RemoteHost(
            session,
            timeout_on_host=credentials.timeout_on_host,
            timeout_in_container=credentials.timeout_in_container,
        )
    except RemoteCommandFailed as exc:
        if type(exc) is not RemoteCommandFailed or session.is_alive():
            raise
        raise ServerConnectionLost(
            output=exc.output, settles_at=exc.settles_at
        ) from exc
    finally:
        session.close()


def bounded(argv: Sequence[str], seconds: float) -> list[str]:
    return [
        TIMEOUT,
        "-k",
        str(settings.REMOTE_KILL_AFTER),
        str(math.ceil(seconds)),
        *argv,
    ]


def _waited(seconds: float, limited: bool) -> float:
    if not limited:
        return seconds
    return seconds + settings.REMOTE_KILL_AFTER + DEADLINE_MARGIN


def _interrupted(exc: BaseException, settles_at: datetime) -> RemoteCommandFailed:
    if isinstance(exc, ConnectionLost):
        return ServerConnectionLost(settles_at=settles_at)
    if isinstance(exc, RemoteTimeout):
        return RemoteCommandTimedOut(settles_at=settles_at)
    return RemoteCommandFailed(settles_at=settles_at)
