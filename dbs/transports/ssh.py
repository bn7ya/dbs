from __future__ import annotations

import base64
import binascii
import datetime
import hashlib
import io
import logging
import os
import posixpath
import socket
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field

from ..exceptions import (
    ConfigurationError,
    ConnectionLost,
    DBSError,
    HostKeyError,
    RemoteTimeout,
)
from ..naming import is_backup_name
from ..tee import (
    is_partial_name,
    is_stale,
    partial_name,
    place_without_replacing,
    sweep_partials,
)

logger = logging.getLogger("dbs")

MAX_CAPTURED_OUTPUT = 64 * 1024
STREAM_CHUNK = 256 * 1024
STDERR_WAIT = 5.0
DEFAULT_KEEPALIVE_INTERVAL = 15.0
DEFAULT_IO_TIMEOUT = 30.0
DEFAULT_COMMAND_TIMEOUT = 6 * 60 * 60.0
KEEPALIVE_REQUEST = "keepalive@openssh.com"
CLOSED_WITHOUT_STATUS = -1
PRIVATE_MODE = 0o600

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
    "host_key",
    "remote_dir",
    "auto_add_host_key",
    "use_agent",
    "connect_timeout",
    "private_key",
    "keepalive_interval",
    "io_timeout",
    "command_timeout",
}


def _paramiko():
    try:
        import paramiko
    except ImportError as exc:
        raise ConfigurationError(
            'SSH transport requires paramiko: pip install "django-dbs[ssh]"'
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


class StreamInterrupted(DBSError):
    pass


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


@dataclass(frozen=True)
class HostKey:
    """A server's public SSH host key, in the form a known_hosts line carries it."""

    key_type: str
    key_base64: str

    @classmethod
    def from_line(cls, line: str) -> "HostKey":
        """Parse ``"<type> <base64> [comment]"``; raise ``ConfigurationError`` if malformed."""
        parts = (line or "").split()
        if len(parts) < 2:
            raise ConfigurationError(
                "A host key must read '<type> <base64>', for example "
                "'ssh-ed25519 AAAAC3Nza...'."
            )
        key_type, key_base64 = parts[0], parts[1]
        if _blob_key_type(key_base64) != key_type:
            raise ConfigurationError(
                f"The host key is not a valid {key_type} public key."
            )
        return cls(key_type, key_base64)

    @property
    def line(self) -> str:
        """The key as ``"<type> <base64>"``, ready to store or to pass as ``host_key``."""
        return f"{self.key_type} {self.key_base64}"

    @property
    def fingerprint(self) -> str:
        """The ``SHA256:`` fingerprint, exactly as ``ssh-keygen -lf`` prints it."""
        digest = hashlib.sha256(base64.b64decode(self.key_base64)).digest()
        return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


def _blob_key_type(key_base64: str) -> str | None:
    try:
        blob = base64.b64decode(key_base64, validate=True)
    except (binascii.Error, ValueError):
        return None
    if len(blob) < 4:
        return None
    length = int.from_bytes(blob[:4], "big")
    if length == 0 or len(blob) < 4 + length:
        return None
    return blob[4 : 4 + length].decode("ascii", "replace")


@dataclass
class SSHTarget:
    host: str
    username: str
    port: int = 22
    key_filename: str | None = None
    key_passphrase: str | None = None
    private_key: str | None = None
    password: str | None = None
    known_hosts: str | None = None
    host_key: str | None = None
    remote_dir: str = "."
    auto_add_host_key: bool = False
    use_agent: bool = True
    connect_timeout: float = 30.0
    keepalive_interval: float = DEFAULT_KEEPALIVE_INTERVAL
    io_timeout: float = DEFAULT_IO_TIMEOUT
    command_timeout: float = DEFAULT_COMMAND_TIMEOUT

    def __post_init__(self):
        self.key_filename = _expand(self.key_filename)
        self.known_hosts = _expand(self.known_hosts)
        if self.keepalive_interval < 0 or self.io_timeout <= 0 or self.command_timeout <= 0:
            raise ConfigurationError(
                f"SSH target {self.host!r} needs a keepalive_interval of 0 or more, and "
                "an io_timeout and a command_timeout above 0 seconds."
            )
        if self.host_key:
            if self.auto_add_host_key:
                raise ConfigurationError(
                    f"SSH target {self.host!r} pins a host_key and also sets "
                    "auto_add_host_key; a pinned key trusts exactly one key, so "
                    "drop auto_add_host_key."
                )
            self.host_key = HostKey.from_line(self.host_key).line
        if (
            not self.key_filename
            and not self.private_key
            and not self.password
            and not self.use_agent
        ):
            raise ConfigurationError(
                f"SSH target {self.host!r} has no way to authenticate: set a "
                "key_filename, a private_key, a password, or leave use_agent "
                "enabled."
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
            private_key=data.get("private_key"),
            password=_from_env(data.get("password_env")) or data.get("password"),
            known_hosts=data.get("known_hosts"),
            host_key=data.get("host_key"),
            remote_dir=data.get("remote_dir", "."),
            auto_add_host_key=bool(data.get("auto_add_host_key", False)),
            use_agent=bool(data.get("use_agent", True)),
            connect_timeout=float(data.get("connect_timeout", 30.0)),
            keepalive_interval=float(
                data.get("keepalive_interval", DEFAULT_KEEPALIVE_INTERVAL)
            ),
            io_timeout=float(data.get("io_timeout", DEFAULT_IO_TIMEOUT)),
            command_timeout=float(data.get("command_timeout", DEFAULT_COMMAND_TIMEOUT)),
        )

    @property
    def host_key_policy(self) -> str:
        if self.host_key:
            return "pinned"
        return "auto-add" if self.auto_add_host_key else "reject-unknown"


def _load_private_key(paramiko, target: SSHTarget):
    if not target.private_key:
        return None
    failures = []
    for key_class in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey):
        try:
            return key_class.from_private_key(
                io.StringIO(target.private_key), password=target.key_passphrase
            )
        except paramiko.PasswordRequiredException as exc:
            raise ConfigurationError(
                "The stored private key is encrypted; set its key passphrase too."
            ) from exc
        except (paramiko.SSHException, ValueError) as exc:
            failures.append(f"{key_class.__name__}: {exc}")
    raise ConfigurationError(
        "The stored private key could not be read as an Ed25519, ECDSA or RSA key; "
        "check the key and its passphrase. " + "; ".join(failures)
    )


def _known_hosts_name(target: SSHTarget) -> str:
    return target.host if target.port == 22 else f"[{target.host}]:{target.port}"


def _untrusted_host_policy(paramiko):
    class RejectUntrustedHost(paramiko.RejectPolicy):
        def missing_host_key(self, client, hostname, key):
            raise HostKeyError(
                f"The host key {hostname} presented is not trusted. Pin it with "
                "host_key, list it in known_hosts, or set auto_add_host_key."
            )

    return RejectUntrustedHost()


def _trust_host_keys(paramiko, client, target: SSHTarget) -> None:
    if target.host_key:
        pinned = HostKey.from_line(target.host_key)
        name = _known_hosts_name(target)
        entry = paramiko.hostkeys.HostKeyEntry.from_line(f"{name} {pinned.line}")
        if entry is None:
            raise ConfigurationError(f"The pinned host key for {target.host} is invalid.")
        client.get_host_keys().add(name, pinned.key_type, entry.key)
    elif target.known_hosts:
        try:
            client.load_host_keys(target.known_hosts)
        except OSError as exc:
            raise ConfigurationError(
                f"Cannot read the known_hosts file {target.known_hosts}: {exc}"
            ) from exc
    else:
        client.load_system_host_keys()
    client.set_missing_host_key_policy(
        paramiko.AutoAddPolicy()
        if target.auto_add_host_key
        else _untrusted_host_policy(paramiko)
    )


def _connect(target: SSHTarget):
    paramiko = _paramiko()
    client = paramiko.SSHClient()
    _trust_host_keys(paramiko, client, target)
    pkey = _load_private_key(paramiko, target)
    try:
        client.connect(
            hostname=target.host,
            port=target.port,
            username=target.username,
            password=target.password,
            key_filename=target.key_filename,
            pkey=pkey,
            passphrase=target.key_passphrase,
            allow_agent=target.use_agent,
            look_for_keys=target.use_agent
            and target.key_filename is None
            and pkey is None,
            timeout=target.connect_timeout,
            banner_timeout=target.connect_timeout,
            auth_timeout=target.connect_timeout,
        )
    except HostKeyError:
        client.close()
        raise
    except paramiko.BadHostKeyException as exc:
        client.close()
        raise HostKeyError(
            f"The host key {target.host} presented does not match the trusted key. "
            "Either the server was reinstalled or something is intercepting the "
            "connection; confirm which before trusting the new key."
        ) from exc
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
    _keep_alive(client, target)
    return client


def _keep_alive(client, target: SSHTarget) -> None:
    transport = client.get_transport()
    if transport is None:
        return
    if target.keepalive_interval > 0:
        transport.set_keepalive(max(1, round(target.keepalive_interval)))
    _drop_when_unanswered(transport.sock, target.io_timeout)


def _drop_when_unanswered(sock, seconds: float) -> None:
    setsockopt = getattr(sock, "setsockopt", None)
    if setsockopt is None:
        return
    options = [(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)]
    if hasattr(socket, "TCP_USER_TIMEOUT"):
        options.append(
            (socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT, int(seconds * 1000))
        )
    for level, option, value in options:
        try:
            setsockopt(level, option, value)
        except OSError:
            return


@contextmanager
def _upload_source(data_or_path):
    if isinstance(data_or_path, (bytes, bytearray)):
        yield io.BytesIO(data_or_path), len(data_or_path)
        return
    if isinstance(data_or_path, (str, os.PathLike)):
        with open(data_or_path, "rb") as fh:
            yield fh, os.fstat(fh.fileno()).st_size
        return
    data_or_path.seek(0)
    size = data_or_path.seek(0, io.SEEK_END)
    data_or_path.seek(0)
    yield data_or_path, size


def _decode(stream) -> str:
    return stream.read(MAX_CAPTURED_OUTPUT).decode("utf-8", "replace")


@dataclass
class SSHSession:
    """An open SSH connection to a backup host, reused across operations."""

    target: SSHTarget
    _client: object = field(default=None, repr=False)
    _sftp: object = field(default=None, repr=False)
    on_activity: Callable[[int], None] | None = field(default=None, repr=False)
    _ticker: object = field(default=None, repr=False)

    def __enter__(self) -> "SSHSession":
        if self._client is None:
            self._client = _connect(self.target)
            if self.on_activity is not None and self.target.keepalive_interval > 0:
                self._ticker = _Ticker(self)
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self._ticker is not None:
            self._ticker.stop()
        if self._client is not None:
            self._client.close()
        self._client = None
        self._sftp = None
        self._ticker = None

    @property
    def sftp(self):
        if self._sftp is None:
            sftp = self._client.open_sftp()
            sftp.get_channel().settimeout(self.target.io_timeout)
            self._sftp = (
                sftp if self.on_activity is None else _MeteredSFTP(sftp, self.on_activity)
            )
        return self._sftp

    def is_alive(self) -> bool:
        transport = self._transport()
        return transport is not None and transport.is_active()

    def answers(self) -> bool:
        transport = self._transport()
        if transport is None or not transport.is_active():
            return False
        try:
            transport.global_request(KEEPALIVE_REQUEST, wait=True)
        except (_paramiko().SSHException, OSError, EOFError):
            return False
        return transport.is_active()

    def _transport(self):
        return None if self._client is None else self._client.get_transport()

    def ensure_dir(self) -> str:
        _ensure_remote_dir(self.sftp, self.target.remote_dir)
        return self.target.remote_dir

    def path_for(self, remote_name: str) -> str:
        return posixpath.join(self.target.remote_dir, remote_name)

    def push(self, data_or_path, remote_name: str) -> str:
        remote_path = self.path_for(remote_name)
        partial = self.path_for(partial_name(remote_name))
        try:
            self.ensure_dir()
            self.sweep_partials()
            _create_private_remote(self.sftp, partial)
            with _upload_source(data_or_path) as (source, size):
                self.sftp.putfo(source, partial)
            _install_remote(self.sftp, partial, remote_path)
        except OSError as exc:
            self._discard_remote(partial)
            raise DBSError(f"SFTP upload failed: {exc}") from exc
        except DBSError:
            self._discard_remote(partial)
            raise
        logger.info(
            "pushed %d bytes to %s:%s", size, self.target.host, remote_path
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
        if os.path.lexists(local_path):
            raise DBSError(f"{local_path} already exists; nothing was overwritten.")
        directory = os.path.dirname(os.path.abspath(local_path))
        sweep_partials(directory)
        partial = os.path.join(directory, partial_name(os.path.basename(local_path)))
        try:
            with _private_local_file(partial) as handle:
                self.sftp.getfo(remote_path, handle)
            _require_backup(partial, remote_name)
            if not place_without_replacing(partial, local_path):
                raise DBSError(f"{local_path} already exists; nothing was overwritten.")
        except OSError as exc:
            raise DBSError(f"SFTP download failed: {exc}") from exc
        finally:
            _discard(partial)
        size = os.path.getsize(local_path)
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

    def sweep_partials(self, now: float | None = None) -> list[str]:
        try:
            entries = self.sftp.listdir_attr(self.target.remote_dir)
        except OSError:
            return []
        removed = []
        for entry in entries:
            if not is_partial_name(entry.filename) or not entry.st_mtime:
                continue
            if not is_stale(entry.st_mtime, now):
                continue
            if self._discard_remote(self.path_for(entry.filename)):
                removed.append(entry.filename)
        return sorted(removed)

    def stream(
        self,
        command: str,
        sink,
        *,
        stdin_line: str | None = None,
        timeout: float | None = None,
        progress=None,
    ) -> RemoteResult:
        guarded = _Guarded(self.target.command_timeout if timeout is None else timeout)
        stdin, stdout, stderr = guarded(
            lambda: self._client.exec_command(command, get_pty=False)
        )
        channel = stdout.channel
        tail = _StderrTail(stderr)
        finished = False
        try:
            guarded(lambda: _send_line(stdin, stdin_line))
            tail.start()
            received = 0
            while True:
                data = guarded(lambda: guarded.receive(channel))
                if not data:
                    break
                sink.write(data)
                received += len(data)
                self._moved(len(data))
                if progress is not None:
                    progress(received)
            status = guarded(lambda: guarded.exit_status(channel))
            if status == CLOSED_WITHOUT_STATUS:
                raise StreamInterrupted("The connection closed before the command finished.")
            finished = True
        finally:
            if not finished:
                _close_quietly(channel)
        tail.join(STDERR_WAIT)
        return RemoteResult(status, "", tail.text())

    def _moved(self, count: int) -> None:
        if self.on_activity is not None:
            self.on_activity(count)

    def _discard_remote(self, remote_path: str) -> bool:
        try:
            self.sftp.remove(remote_path)
        except (OSError, IOError):
            return False
        return True

    def run(
        self,
        command: str,
        *,
        stdin_line: str | None = None,
        timeout: float | None = None,
    ) -> RemoteResult:
        limit = self.target.command_timeout if timeout is None else timeout
        try:
            stdin, stdout, stderr = self._client.exec_command(
                command, timeout=limit, get_pty=False
            )
        except socket.timeout as exc:
            raise RemoteTimeout(f"Remote command timed out after {limit}s.") from exc
        except (_paramiko().SSHException, OSError) as exc:
            raise self._failure(exc) from exc
        deadline = _Deadline(stdout.channel, limit)
        try:
            if stdin_line is not None:
                stdin.write(stdin_line + "\n")
                stdin.flush()
            stdin.channel.shutdown_write()
            out = _decode(stdout)
            err = _decode(stderr)
            status = stdout.channel.recv_exit_status()
        except (socket.timeout, OSError) as exc:
            if deadline.passed or isinstance(exc, socket.timeout):
                raise RemoteTimeout(f"Remote command timed out after {limit}s.") from exc
            raise self._failure(exc) from exc
        finally:
            deadline.cancel()
        if deadline.passed:
            raise RemoteTimeout(f"Remote command timed out after {limit}s.")
        if status == CLOSED_WITHOUT_STATUS and not self.is_alive():
            raise self._lost()
        return RemoteResult(status, out, err)

    def _failure(self, exc: BaseException) -> DBSError:
        if not self.is_alive():
            return self._lost()
        return DBSError(f"Remote command failed: {exc}")

    def _lost(self) -> ConnectionLost:
        return ConnectionLost(
            f"The connection to {self.target.host} was lost while a command ran."
        )


class _Ticker:
    def __init__(self, session: SSHSession):
        self._session = session
        self._stopped = threading.Event()
        self._thread = threading.Thread(
            target=self._beat, name="dbs-ssh-liveness", daemon=True
        )
        self._thread.start()

    def _beat(self) -> None:
        while not self._stopped.wait(self._session.target.keepalive_interval):
            if not self._session.answers() or self._stopped.is_set():
                return
            self._session.on_activity(0)

    def stop(self) -> None:
        self._stopped.set()


class _MeteredSFTP:
    def __init__(self, sftp, moved: Callable[[int], None]):
        self._sftp = sftp
        self._moved = moved

    def __getattr__(self, name):
        return getattr(self._sftp, name)

    def open(self, *args, **kwargs):
        return _MeteredFile(self._sftp.open(*args, **kwargs), self._moved)

    def get(self, *args, callback=None, **kwargs):
        return self._sftp.get(*args, callback=self._counted(callback), **kwargs)

    def getfo(self, *args, callback=None, **kwargs):
        return self._sftp.getfo(*args, callback=self._counted(callback), **kwargs)

    def put(self, *args, callback=None, **kwargs):
        return self._sftp.put(*args, callback=self._counted(callback), **kwargs)

    def putfo(self, *args, callback=None, **kwargs):
        return self._sftp.putfo(*args, callback=self._counted(callback), **kwargs)

    def _counted(self, callback):
        reached = [0]

        def counted(done, total):
            self._moved(max(done - reached[0], 0))
            reached[0] = done
            if callback is not None:
                callback(done, total)

        return counted


class _MeteredFile:
    def __init__(self, handle, moved: Callable[[int], None]):
        self._handle = handle
        self._moved = moved

    def __getattr__(self, name):
        return getattr(self._handle, name)

    def __enter__(self):
        self._handle.__enter__()
        return self

    def __exit__(self, *exc):
        return self._handle.__exit__(*exc)

    def read(self, *args):
        data = self._handle.read(*args)
        self._moved(len(data))
        return data

    def readv(self, *args, **kwargs):
        for piece in self._handle.readv(*args, **kwargs):
            self._moved(len(piece))
            yield piece

    def write(self, data):
        self._handle.write(data)
        self._moved(len(data))


class _Deadline:
    def __init__(self, channel, timeout: float | None):
        self._expired = threading.Event()
        self._timer = None
        if timeout:
            self._timer = threading.Timer(timeout, self._expire, args=(channel,))
            self._timer.daemon = True
            self._timer.start()

    def _expire(self, channel) -> None:
        self._expired.set()
        channel.close()

    @property
    def passed(self) -> bool:
        return self._expired.is_set()

    def cancel(self) -> None:
        if self._timer is not None:
            self._timer.cancel()


def fetch_host_key(host: str, port: int = 22, *, timeout: float = 10.0) -> HostKey:
    """Read the host key ``host`` presents, without authenticating, so a person can confirm it before it is pinned."""
    paramiko = _paramiko()
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except OSError as exc:
        raise DBSError(f"Cannot reach {host}:{port}: {exc}") from exc
    transport = paramiko.Transport(sock)
    transport.banner_timeout = timeout
    try:
        transport.start_client(timeout=timeout)
        key = transport.get_remote_server_key()
    except (paramiko.SSHException, OSError, EOFError) as exc:
        raise DBSError(f"SSH handshake with {host}:{port} failed: {exc}") from exc
    finally:
        transport.close()
    return HostKey(key.get_name(), key.get_base64())


def open_session(target: SSHTarget) -> SSHSession:
    """Build an SSH session for ``target``; enter it as a context manager to connect."""
    return SSHSession(target)


def push_backup(data_or_path, remote_name: str, target: SSHTarget) -> str:
    """Upload backup bytes, a local file or an open binary file to ``target``; return the remote path."""
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


def _private_local_file(path: str):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, PRIVATE_MODE)
    try:
        os.fchmod(descriptor, PRIVATE_MODE)
    except OSError:
        os.close(descriptor)
        raise
    return os.fdopen(descriptor, "wb")


def _create_private_remote(sftp, path: str) -> None:
    sftp.putfo(io.BytesIO(b""), path)
    sftp.chmod(path, PRIVATE_MODE)


def _install_remote(sftp, partial: str, remote_path: str) -> None:
    try:
        sftp.stat(remote_path)
    except FileNotFoundError:
        sftp.rename(partial, remote_path)
        return
    raise DBSError(f"{remote_path} already exists on the server; nothing was overwritten.")


def _require_backup(path: str, name: str) -> None:
    from ..engine.validate import validate_backup

    result = validate_backup(path)
    if not result.ok:
        raise DBSError(f"{name} is not a valid DBS backup: {result.summary()}")


class _Guarded:
    def __init__(self, timeout: float | None):
        self.timeout = timeout
        self.deadline = None if not timeout else time.monotonic() + timeout
        self.lost = (OSError, EOFError, _paramiko().SSHException)

    def __call__(self, action):
        try:
            return action()
        except socket.timeout as exc:
            raise StreamInterrupted(
                f"Remote command timed out after {self.timeout}s."
            ) from exc
        except self.lost as exc:
            raise StreamInterrupted(f"The connection was lost: {exc}") from exc

    def remaining(self) -> float | None:
        if self.deadline is None:
            return None
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise socket.timeout()
        return left

    def receive(self, channel) -> bytes:
        channel.settimeout(self.remaining())
        return channel.recv(STREAM_CHUNK)

    def exit_status(self, channel) -> int:
        if self.deadline is not None and not channel.status_event.wait(
            self.remaining()
        ):
            raise socket.timeout()
        return channel.recv_exit_status()


def _send_line(stdin, line: str | None) -> None:
    if line is not None:
        stdin.write(line + "\n")
        stdin.flush()
    stdin.channel.shutdown_write()


def _close_quietly(channel) -> None:
    try:
        channel.close()
    except Exception:
        pass


class _StderrTail:
    def __init__(self, stream, limit: int = MAX_CAPTURED_OUTPUT):
        self._stream = stream
        self._limit = limit
        self._kept = bytearray()
        self._thread = threading.Thread(target=self._read, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def join(self, timeout: float) -> None:
        if self._thread.is_alive():
            self._thread.join(timeout)

    def text(self) -> str:
        return bytes(self._kept).decode("utf-8", "replace")

    def _read(self) -> None:
        try:
            while True:
                chunk = self._stream.read(STREAM_CHUNK)
                if not chunk:
                    return
                self._kept += chunk
                del self._kept[: max(len(self._kept) - self._limit, 0)]
        except Exception:
            return


def _ensure_remote_dir(sftp, remote_dir: str) -> None:
    parts = [p for p in remote_dir.split("/") if p]
    path = "/" if remote_dir.startswith("/") else ""
    for part in parts:
        path = posixpath.join(path, part) if path else part
        try:
            sftp.stat(path)
        except FileNotFoundError:
            sftp.mkdir(path)
