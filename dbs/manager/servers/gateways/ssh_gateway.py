from __future__ import annotations

import base64
import os
import posixpath
import re
import secrets
import shlex
import stat
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import datetime
from datetime import timezone as dt_timezone
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, cast

from django.conf import settings
from django.views.decorators.debug import sensitive_variables
from paramiko import Channel, PKey, SFTPAttributes, SFTPClient, SFTPFile, SSHException
from paramiko.pkey import UnknownKeyType

from dbs import validate_backup
from dbs.client import BackupOptions, ServerProfile, backup_and_fetch
from dbs.client.remote import available_local_name
from dbs.exceptions import ConfigurationError, DBSError
from dbs.manager.servers.exceptions import (
    ArchiveFailed,
    BackupInvalid,
    DbsTooOld,
    FileExists,
    FileTooLarge,
    FolderNotEmpty,
    HostKeyChanged,
    RemoteCommandFailed,
    RemoteNotFound,
    RemotePermissionDenied,
    RestoreFailed,
    SSHAuthFailed,
    SSHUnreachable,
)
from dbs.transports import HostKey, HostKeyError, RemoteResult, SSHSession, SSHTarget
from dbs.transports import fetch_host_key as dbs_fetch_host_key

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
RESTORED = re.compile(r"Restored (\d+) records and (\d+) files")
WOULD_RESTORE = re.compile(r"(\d+) records and (\d+) files would be restored")
FLUSHED = re.compile(r"Flushed (\d+) existing rows")
WOULD_FLUSH = re.compile(r"Flush would first delete (\d+) existing rows")
HEALED = "Corruption detected and repaired"
UNKNOWN_OPTION = "unrecognized arguments"
RESTORE_FILE_PREFIX = ".dbs-restore-"
RESTORE_FILE_MODE = 0o600
EXTRACT_FILE_PREFIX = ".dbs-extract-"
ARCHIVE_SUFFIX = ".tar.gz"
REMOTE_DIRECTORY_MODE = 0o700
PARTIAL_FILE_MODE = 0o600
TRANSFER_WINDOW = 4 * 1024 * 1024
NAME_MAX_BYTES = 255
PARTIAL_NAME_BYTES = NAME_MAX_BYTES - len(".") - len(".part-") - 16


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


@dataclass(frozen=True)
class DbsProfile:
    python: str
    manage: str
    project_dir: str | None = None
    settings_module: str | None = None


@dataclass(frozen=True)
class FetchedBackup:
    local_path: str
    remote_path: str


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


class RemoteReader:
    def __init__(self, handle: SFTPFile) -> None:
        self._handle: SFTPFile = handle

    def read(self, size: int = -1) -> bytes:
        try:
            return self._handle.read(size)
        except TRANSPORT_ERRORS as exc:
            raise RemoteCommandFailed() from exc


class RemoteHost:
    def __init__(self, session: SSHSession) -> None:
        self.session = session

    @property
    def sftp(self) -> SFTPClient:
        try:
            sftp: SFTPClient = self.session.sftp
            cast(Channel, sftp.get_channel()).settimeout(settings.SSH_COMMAND_TIMEOUT)
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
    ) -> RemoteResult:
        script = build_script(argv, cwd=cwd, env=env)
        try:
            return self.session.run(
                script,
                stdin_line=stdin_line,
                timeout=timeout or settings.SSH_COMMAND_TIMEOUT,
            )
        except TRANSPORT_ERRORS as exc:
            raise RemoteCommandFailed() from exc

    def take_dbs_backup(
        self,
        *,
        profile: DbsProfile,
        passphrase: str,
        dest_dir: str,
        prefix: str,
        keep_remote: int,
    ) -> FetchedBackup:
        self.sftp
        target = self.session.target
        name = available_local_name(dest_dir, prefix)
        local_path = os.path.join(dest_dir, name)
        server = ServerProfile(
            name=prefix,
            host=target.host,
            port=target.port,
            username=target.username,
            use_agent=False,
            remote_dir=target.remote_dir,
            project_dir=profile.project_dir,
            python=profile.python,
            manage=profile.manage,
            django_settings_module=profile.settings_module,
            prefix=prefix,
            passphrase_transport="stdin",
            exec_timeout=settings.BACKUP_EXEC_TIMEOUT,
        )
        try:
            backup_and_fetch(
                server,
                passphrase,
                dest_dir=dest_dir,
                name=name,
                session=self.session,
                options=BackupOptions(),
                delete_remote=keep_remote == 0,
                keep_remote=keep_remote or None,
                validate=False,
            )
        except TRANSPORT_ERRORS as exc:
            Path(local_path).unlink(missing_ok=True)
            raise RemoteCommandFailed(output=_tail(str(exc), passphrase)) from exc

        structure = validate_backup(Path(local_path).read_bytes())
        if not structure.ok:
            Path(local_path).unlink(missing_ok=True)
            raise BackupInvalid(output=_tail(structure.summary(), passphrase))
        remote_path = self.session.path_for(name) if keep_remote else ""
        return FetchedBackup(local_path=local_path, remote_path=remote_path)

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
        path = posixpath.join(remote_dir, name)
        self._make_dirs(remote_dir)
        self.write_new(source, remote_dir, name, mode=RESTORE_FILE_MODE)
        argv = [
            profile.python,
            profile.manage,
            "dbs_restore",
            path,
            "--passphrase-stdin",
        ]
        argv += ["--flush"] if flush else []
        argv += ["--dry-run"] if dry_run else []
        env = (
            {"DJANGO_SETTINGS_MODULE": profile.settings_module}
            if profile.settings_module
            else None
        )
        try:
            result = self.run(
                argv,
                cwd=profile.project_dir,
                env=env,
                stdin_line=passphrase,
                timeout=settings.BACKUP_EXEC_TIMEOUT,
            )
        finally:
            copy_left = self._removed_or_left(path)
        if not result.ok:
            output = _tail(f"{result.stdout}\n{result.stderr}", passphrase)
            if UNKNOWN_OPTION in result.stderr:
                raise DbsTooOld(output=output)
            raise RestoreFailed(output=output)
        return _restore_report(
            result.stdout, flush=flush, dry_run=dry_run, copy_left=copy_left
        )

    def extract_archive(
        self,
        source: SupportsRead[bytes],
        remote_dir: str,
        timeout: float,
        relocate: Mapping[str, str] | None = None,
    ) -> str:
        name = f"{EXTRACT_FILE_PREFIX}{secrets.token_hex(8)}{ARCHIVE_SUFFIX}"
        path = posixpath.join(remote_dir, name)
        self._make_dirs(remote_dir)
        self.write_new(source, remote_dir, name, mode=RESTORE_FILE_MODE)
        try:
            result = self.run(
                [
                    "tar",
                    "-xzf",
                    path,
                    "-C",
                    "/",
                    "--no-same-owner",
                    *_transforms(relocate or {}),
                ],
                timeout=timeout,
            )
        finally:
            copy_left = self._removed_or_left(path)
        if not result.ok:
            raise ArchiveFailed(output=_tail(result.stderr or result.stdout))
        return copy_left

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

    @contextmanager
    def stream_file(
        self, path: str, limit: int | None = None
    ) -> Iterator[Iterator[bytes]]:
        sftp = self.sftp
        try:
            handle = sftp.open(path, "rb")
        except SFTP_ERRORS as exc:
            raise _translated(exc, path) from exc
        try:
            yield _windows(handle, limit)
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
        result = self.run(["sha256sum", "--", path], timeout=timeout)
        found = SHA256SUM_LINE.match(result.stdout) if result.ok else None
        if found is None:
            raise RemoteCommandFailed(output=_tail(result.stderr or result.stdout))
        return found.group(1)


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


def _partial_name(name: str) -> str:
    kept = name.encode()[:PARTIAL_NAME_BYTES].decode(errors="ignore")
    return f".{kept}.part-{secrets.token_hex(8)}"


def _windows(handle: SFTPFile, limit: int | None) -> Iterator[bytes]:
    offset = 0
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
        )
        session = SSHSession(target).__enter__()
    except HostKeyError as exc:
        raise HostKeyChanged() from exc
    except ConfigurationError as exc:
        raise SSHAuthFailed() from exc
    except DBSError as exc:
        raise SSHUnreachable() from exc
    try:
        yield RemoteHost(session)
    finally:
        session.close()


def _sed_literal(text: str) -> str:
    return re.sub(r"([\\.\[\]*^$|])", r"\\\1", text)


def _transforms(relocate: Mapping[str, str]) -> list[str]:
    rules = []
    for old, new in relocate.items():
        old_member = posixpath.normpath(old).strip("/")
        new_member = posixpath.normpath(new).strip("/")
        if not old_member or not new_member or old_member == new_member:
            continue
        replacement = new_member.replace("\\", "\\\\").replace("|", "\\|").replace("&", "\\&")
        rules.append(f"--transform=s|^{_sed_literal(old_member)}/|{replacement}/|")
    return rules
