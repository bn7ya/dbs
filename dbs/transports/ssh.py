from __future__ import annotations

import datetime
import io
import logging
import os
import posixpath
import socket
from dataclasses import dataclass, field

from ..conf import setting
from ..exceptions import ConfigurationError, DBSError
from ..naming import is_backup_name

logger = logging.getLogger("dbs")

MAX_CAPTURED_OUTPUT = 64 * 1024

_TARGET_KEYS = {
    "host",
    "username",
    "user",
    "port",
    "key_filename",
    "key_file",
    "key_passphrase",
    "key_passphrase_env",
    "password",
    "password_env",
    "known_hosts",
    "remote_dir",
    "auto_add_host_key",
    "use_agent",
    "connect_timeout",
}


def _paramiko():
    try:
        import paramiko
    except ImportError as exc:
        raise ConfigurationError(
            'SSH transport requires paramiko: pip install "django-dbs[client]"'
        ) from exc
    return paramiko


def _from_env(name: str | None) -> str | None:
    if not name:
        return None
    value = os.environ.get(name)
    if value is None:
        raise ConfigurationError(f"Environment variable {name!r} is not set.")
    return value


def _expand(path: str | None) -> str | None:
    return os.path.expanduser(path) if path else path


@dataclass
class RemoteBackup:
    name: str
    size: int
    modified: datetime.datetime | None = None


@dataclass
class RemoteResult:
    exit_status: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_status == 0


@dataclass
class SSHTarget:
    host: str
    username: str
    port: int = 22
    key_filename: str | None = None
    key_passphrase: str | None = None
    password: str | None = None
    known_hosts: str | None = None
    remote_dir: str = "."
    auto_add_host_key: bool = False
    use_agent: bool = True
    connect_timeout: float = 30.0

    def __post_init__(self):
        self.key_filename = _expand(self.key_filename)
        self.known_hosts = _expand(self.known_hosts)
        if not self.key_filename and not self.password and not self.use_agent:
            raise ConfigurationError(
                f"SSH target {self.host!r} has no way to authenticate: set a "
                "key_filename, a password, or leave use_agent enabled."
            )

    @classmethod
    def from_dict(cls, data: dict) -> "SSHTarget":
        unknown = set(data) - _TARGET_KEYS
        if unknown:
            raise ConfigurationError(
                f"Unknown SSH target keys: {', '.join(sorted(unknown))}."
            )
        try:
            host = data["host"]
            username = data.get("username") or data["user"]
        except KeyError as exc:
            raise ConfigurationError(f"SSH target missing required key: {exc}") from exc
        return cls(
            host=host,
            username=username,
            port=int(data.get("port", 22)),
            key_filename=data.get("key_filename") or data.get("key_file"),
            key_passphrase=(
                _from_env(data.get("key_passphrase_env"))
                or data.get("key_passphrase")
            ),
            password=_from_env(data.get("password_env")) or data.get("password"),
            known_hosts=data.get("known_hosts"),
            remote_dir=data.get("remote_dir", "."),
            auto_add_host_key=bool(data.get("auto_add_host_key", False)),
            use_agent=bool(data.get("use_agent", True)),
            connect_timeout=float(data.get("connect_timeout", 30.0)),
        )

    @classmethod
    def from_settings(cls, name: str) -> "SSHTarget":
        targets = setting("DBS_SSH_TARGETS", {}) or {}
        if name not in targets:
            raise ConfigurationError(f"No DBS_SSH_TARGETS entry named {name!r}.")
        return cls.from_dict(targets[name])

    @property
    def host_key_policy(self) -> str:
        return "auto-add" if self.auto_add_host_key else "reject-unknown"


def _connect(target: SSHTarget):
    paramiko = _paramiko()
    client = paramiko.SSHClient()
    if target.known_hosts:
        try:
            client.load_host_keys(target.known_hosts)
        except OSError as exc:
            raise ConfigurationError(
                f"Cannot read the known_hosts file {target.known_hosts}: {exc}"
            ) from exc
    else:
        client.load_system_host_keys()
    client.set_missing_host_key_policy(
        paramiko.AutoAddPolicy() if target.auto_add_host_key else paramiko.RejectPolicy()
    )
    try:
        client.connect(
            hostname=target.host,
            port=target.port,
            username=target.username,
            password=target.password,
            key_filename=target.key_filename,
            passphrase=target.key_passphrase,
            allow_agent=target.use_agent,
            look_for_keys=target.key_filename is None,
            timeout=target.connect_timeout,
            banner_timeout=target.connect_timeout,
            auth_timeout=target.connect_timeout,
        )
    except paramiko.PasswordRequiredException as exc:
        raise ConfigurationError(
            f"The private key {target.key_filename} is encrypted; set key_passphrase "
            "or key_passphrase_env."
        ) from exc
    except paramiko.AuthenticationException as exc:
        raise ConfigurationError(
            f"SSH authentication failed for {target.username}@{target.host}: {exc}"
        ) from exc
    except paramiko.SSHException as exc:
        if target.key_filename:
            raise ConfigurationError(
                f"Could not use the private key {target.key_filename}; check "
                f"key_passphrase and that the key format is supported: {exc}"
            ) from exc
        raise DBSError(f"SSH connection to {target.host} failed: {exc}") from exc
    except (OSError, socket.error) as exc:
        raise DBSError(f"Cannot reach {target.host}:{target.port}: {exc}") from exc
    return client


def _as_bytes(data_or_path: bytes | str) -> bytes:
    if isinstance(data_or_path, (bytes, bytearray)):
        return bytes(data_or_path)
    with open(data_or_path, "rb") as fh:
        return fh.read()


def _decode(stream) -> str:
    return stream.read(MAX_CAPTURED_OUTPUT).decode("utf-8", "replace")


@dataclass
class SSHSession:
    """An open SSH connection to a backup host, reused across operations."""

    target: SSHTarget
    _client: object = field(default=None, repr=False)
    _sftp: object = field(default=None, repr=False)

    def __enter__(self) -> "SSHSession":
        if self._client is None:
            self._client = _connect(self.target)
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
        self._client = None
        self._sftp = None

    @property
    def sftp(self):
        if self._sftp is None:
            self._sftp = self._client.open_sftp()
        return self._sftp

    def ensure_dir(self) -> str:
        _ensure_remote_dir(self.sftp, self.target.remote_dir)
        return self.target.remote_dir

    def path_for(self, remote_name: str) -> str:
        return posixpath.join(self.target.remote_dir, remote_name)

    def push(self, data_or_path: bytes | str, remote_name: str) -> str:
        data = _as_bytes(data_or_path)
        remote_path = self.path_for(remote_name)
        partial = f"{remote_path}.part"
        try:
            self.ensure_dir()
            self.sftp.putfo(io.BytesIO(data), partial)
            _replace_remote(self.sftp, partial, remote_path)
        except OSError as exc:
            raise DBSError(f"SFTP upload failed: {exc}") from exc
        logger.info(
            "pushed %d bytes to %s:%s", len(data), self.target.host, remote_path
        )
        return remote_path

    def pull(self, remote_name: str) -> bytes:
        remote_path = self.path_for(remote_name)
        buffer = io.BytesIO()
        try:
            self.sftp.getfo(remote_path, buffer)
        except OSError as exc:
            raise DBSError(f"SFTP download failed: {exc}") from exc
        data = buffer.getvalue()
        logger.info(
            "pulled %d bytes from %s:%s", len(data), self.target.host, remote_path
        )
        return data

    def pull_to(self, remote_name: str, local_path: str) -> int:
        remote_path = self.path_for(remote_name)
        partial = f"{local_path}.part"
        try:
            self.sftp.get(remote_path, partial)
        except OSError as exc:
            _discard(partial)
            raise DBSError(f"SFTP download failed: {exc}") from exc
        size = os.path.getsize(partial)
        os.replace(partial, local_path)
        logger.info(
            "pulled %d bytes from %s:%s to %s",
            size,
            self.target.host,
            remote_path,
            local_path,
        )
        return size

    def names(self, pattern_only: bool = True) -> list[str]:
        try:
            entries = self.sftp.listdir(self.target.remote_dir)
        except OSError as exc:
            raise DBSError(f"SFTP listing failed: {exc}") from exc
        if pattern_only:
            entries = [name for name in entries if is_backup_name(name)]
        return sorted(entries)

    def details(self, pattern_only: bool = True) -> list[RemoteBackup]:
        try:
            entries = self.sftp.listdir_attr(self.target.remote_dir)
        except OSError as exc:
            raise DBSError(f"SFTP listing failed: {exc}") from exc
        backups = []
        for entry in entries:
            if pattern_only and not is_backup_name(entry.filename):
                continue
            modified = (
                datetime.datetime.fromtimestamp(entry.st_mtime, datetime.timezone.utc)
                if entry.st_mtime
                else None
            )
            backups.append(
                RemoteBackup(entry.filename, entry.st_size or 0, modified)
            )
        return sorted(backups, key=lambda backup: backup.name)

    def delete(self, remote_name: str) -> None:
        try:
            self.sftp.remove(self.path_for(remote_name))
        except OSError as exc:
            raise DBSError(f"SFTP delete failed: {exc}") from exc
        logger.info("deleted %s:%s", self.target.host, self.path_for(remote_name))

    def run(
        self,
        command: str,
        *,
        stdin_line: str | None = None,
        timeout: float | None = None,
    ) -> RemoteResult:
        try:
            stdin, stdout, stderr = self._client.exec_command(
                command, timeout=timeout, get_pty=False
            )
            if stdin_line is not None:
                stdin.write(stdin_line + "\n")
                stdin.flush()
            stdin.channel.shutdown_write()
            out = _decode(stdout)
            err = _decode(stderr)
            status = stdout.channel.recv_exit_status()
        except socket.timeout as exc:
            raise DBSError(f"Remote command timed out after {timeout}s.") from exc
        except OSError as exc:
            raise DBSError(f"Remote command failed: {exc}") from exc
        return RemoteResult(status, out, err)


def open_session(target: SSHTarget) -> SSHSession:
    """Build an SSH session for ``target``; enter it as a context manager to connect."""
    return SSHSession(target)


def push_backup(data_or_path: bytes | str, remote_name: str, target: SSHTarget) -> str:
    """Upload backup bytes (or a local file) to ``target``; return the remote path."""
    with SSHSession(target) as session:
        return session.push(data_or_path, remote_name)


def pull_backup(remote_name: str, target: SSHTarget) -> bytes:
    """Download a backup from ``target`` and return its bytes."""
    with SSHSession(target) as session:
        return session.pull(remote_name)


def pull_backup_to(remote_name: str, local_path: str, target: SSHTarget) -> int:
    """Stream a backup from ``target`` to ``local_path``; return the byte count."""
    with SSHSession(target) as session:
        return session.pull_to(remote_name, local_path)


def list_backups(target: SSHTarget, pattern_only: bool = True) -> list[str]:
    """List backup filenames present in the target's remote directory."""
    with SSHSession(target) as session:
        return session.names(pattern_only)


def list_backup_details(target: SSHTarget) -> list[RemoteBackup]:
    """List remote backups with their size and modification time."""
    with SSHSession(target) as session:
        return session.details()


def delete_backup(remote_name: str, target: SSHTarget) -> None:
    """Remove a backup file from the target's remote directory."""
    with SSHSession(target) as session:
        session.delete(remote_name)


def check_connection(target: SSHTarget) -> dict:
    """Connect to ``target`` and report the facts a developer needs to debug it."""
    with SSHSession(target) as session:
        result = session.run("uname -sr")
        session.ensure_dir()
        return {
            "host": target.host,
            "username": target.username,
            "port": target.port,
            "host_key_policy": target.host_key_policy,
            "system": result.stdout.strip() or "unknown",
            "remote_dir": target.remote_dir,
            "backups": len(session.names()),
        }


def _discard(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _replace_remote(sftp, partial: str, remote_path: str) -> None:
    try:
        sftp.remove(remote_path)
    except (OSError, IOError):
        pass
    sftp.rename(partial, remote_path)


def _ensure_remote_dir(sftp, remote_dir: str) -> None:
    parts = [p for p in remote_dir.split("/") if p]
    path = "/" if remote_dir.startswith("/") else ""
    for part in parts:
        path = posixpath.join(path, part) if path else part
        try:
            sftp.stat(path)
        except FileNotFoundError:
            sftp.mkdir(path)
