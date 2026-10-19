"""A paramiko stand-in backed by a real directory, so transports test without a server."""

import errno
import io
import os
import posixpath
import queue
import socket
import threading
import time
import types


class SSHException(Exception):
    pass


class AuthenticationException(SSHException):
    pass


class PasswordRequiredException(AuthenticationException):
    pass


class BadHostKeyException(SSHException):
    def __init__(self, hostname, got_key, expected_key):
        super().__init__(f"Host key for {hostname} does not match")
        self.hostname = hostname
        self.key = got_key
        self.expected_key = expected_key


class AutoAddPolicy:
    def missing_host_key(self, client, hostname, key):
        client.get_host_keys().add(hostname, key.split()[0], key)


class RejectPolicy:
    def missing_host_key(self, client, hostname, key):
        raise SSHException(f"Server {hostname!r} not found in known_hosts")


class FakeHostKeyEntry:
    def __init__(self, hostnames, key):
        self.hostnames = hostnames
        self.key = key

    @classmethod
    def from_line(cls, line):
        fields = line.split(" ")
        if len(fields) < 3:
            return None
        names, key_type, key = fields[:3]
        return cls(names.split(","), f"{key_type} {key}")


class FakeHostKeys(dict):
    def add(self, hostname, keytype, key):
        self.setdefault(hostname, {})[keytype] = key


class FakeServerKey:
    def __init__(self, line):
        self._type, self._base64 = line.split()[:2]

    def get_name(self):
        return self._type

    def get_base64(self):
        return self._base64


class FakeTransport:
    def __init__(self, registry, sock):
        self._registry = registry
        self.sock = sock
        self.banner_timeout = None
        self.start_timeout = None
        self.keepalive = None
        self.closed = False

    def start_client(self, timeout=None):
        self.start_timeout = timeout
        if self._registry.handshake_error is not None:
            raise self._registry.handshake_error

    def get_remote_server_key(self):
        return FakeServerKey(self._registry.presented_key)

    def set_keepalive(self, interval):
        self.keepalive = interval

    def is_active(self):
        return not self.closed and not self._registry.dropped

    def global_request(self, kind, data=None, wait=True):
        self._registry.global_requests.append((kind, wait))
        return None

    def open_session(self, timeout=None):
        channel = FakeTerminalChannel(timeout)
        self._registry.terminals.append(channel)
        return channel

    def close(self):
        self.closed = True


class FakeTerminalChannel:
    """A pseudo-terminal channel whose output a test writes with emit() and ends with exit()."""

    def __init__(self, open_timeout=None):
        self.open_timeout = open_timeout
        self.pty = None
        self.shell = False
        self.command = None
        self.sent = bytearray()
        self.sizes = []
        self.timeout = None
        self.closed = False
        self.status = None
        self.refuse_input = False
        self._output = queue.Queue()

    def get_pty(self, term="vt100", width=80, height=24):
        self.pty = (term, width, height)

    def invoke_shell(self):
        self.shell = True

    def exec_command(self, command):
        self.command = command

    def resize_pty(self, width=80, height=24):
        self.sizes.append((width, height))

    def settimeout(self, timeout):
        self.timeout = timeout

    def sendall(self, data):
        if self.closed or self.refuse_input:
            raise OSError("Socket is closed")
        self.sent += data

    def recv(self, size):
        item = self._output.get()
        if item is None:
            self._output.put(None)
            return b""
        return item

    def emit(self, data):
        self._output.put(data)

    def exit(self, status=0):
        self.status = status
        self._output.put(None)

    def exit_status_ready(self):
        return self.status is not None

    def recv_exit_status(self):
        return -1 if self.status is None else self.status

    def close(self):
        self.closed = True
        self._output.put(None)


class FakeSocket:
    def __init__(self):
        self.options = {}

    def setsockopt(self, level, option, value):
        self.options[(level, option)] = value


class FakeSFTPChannel:
    def __init__(self):
        self.timeout = None

    def settimeout(self, timeout):
        self.timeout = timeout


def _report(callback, moved):
    if callback is not None:
        callback(moved, moved)


class FakeAttr:
    def __init__(self, filename, st_size, st_mtime):
        self.filename = filename
        self.st_size = st_size
        self.st_mtime = st_mtime


class FakeSFTP:
    def __init__(self, root):
        self.root = root
        self.channel = FakeSFTPChannel()

    def get_channel(self):
        return self.channel

    def _local(self, remote_path):
        return os.path.join(self.root, remote_path.lstrip("/"))

    def _missing(self, remote_path):
        return FileNotFoundError(
            errno.ENOENT, "No such file", remote_path
        )

    def putfo(self, handle, remote_path, callback=None):
        local = self._local(remote_path)
        if not os.path.isdir(os.path.dirname(local)):
            raise self._missing(remote_path)
        with open(local, "wb") as fh:
            moved = fh.write(handle.read())
        _report(callback, moved)

    def getfo(self, remote_path, handle, callback=None):
        local = self._local(remote_path)
        if not os.path.exists(local):
            raise self._missing(remote_path)
        with open(local, "rb") as fh:
            moved = handle.write(fh.read())
        _report(callback, moved)

    def get(self, remote_path, local_path, callback=None):
        local = self._local(remote_path)
        if not os.path.exists(local):
            raise self._missing(remote_path)
        with open(local, "rb") as source, open(local_path, "wb") as target:
            moved = target.write(source.read())
        _report(callback, moved)

    def listdir(self, remote_dir):
        local = self._local(remote_dir)
        if not os.path.isdir(local):
            raise self._missing(remote_dir)
        return os.listdir(local)

    def listdir_attr(self, remote_dir):
        local = self._local(remote_dir)
        if not os.path.isdir(local):
            raise self._missing(remote_dir)
        attrs = []
        for name in os.listdir(local):
            info = os.stat(os.path.join(local, name))
            attrs.append(FakeAttr(name, info.st_size, int(info.st_mtime)))
        return attrs

    def stat(self, remote_path):
        local = self._local(remote_path)
        if not os.path.exists(local):
            raise self._missing(remote_path)
        return os.stat(local)

    def mkdir(self, remote_path):
        os.mkdir(self._local(remote_path))

    def remove(self, remote_path):
        local = self._local(remote_path)
        if not os.path.exists(local):
            raise self._missing(remote_path)
        os.remove(local)

    def chmod(self, remote_path, mode):
        os.chmod(self._local(remote_path), mode)

    def rename(self, source, destination):
        os.replace(self._local(source), self._local(destination))


class FakeChannel:
    def __init__(self, session):
        self._session = session
        self.status_event = threading.Event()
        self.status_event.set()

    def shutdown_write(self):
        self._session.stdin_closed = True

    def settimeout(self, timeout):
        self._session.timeouts.append(timeout)

    def recv(self, size):
        data = self._session.take(1, size)
        if data:
            return data
        return self._session.after_quiet()

    def sendall(self, data):
        self._session.sent += data

    def close(self):
        self._session.channel_closed = True

    def recv_exit_status(self):
        return self._session.resolve()[0]


class FakeStdin(io.StringIO):
    def __init__(self, session):
        super().__init__()
        self._session = session
        self.channel = FakeChannel(session)

    def write(self, text):
        self._session.stdin += text
        return len(text)

    def flush(self):
        pass


class FakeStdout:
    def __init__(self, session, index):
        self._session = session
        self._index = index
        self.channel = FakeChannel(session)

    def read(self, size=-1):
        self._session.resolve()
        if self._index == 2 and self._session.stderr_every:
            line = self._session.next_line(2)
            if line:
                time.sleep(self._session.stderr_every)
            return line
        return self._session.take(self._index, size)


class FakeExec:
    def __init__(self, registry, command):
        self._registry = registry
        self._outcome = None
        self.command = command
        self.stdin = ""
        self.sent = bytearray()
        self.stdin_closed = False
        self.channel_closed = False
        self.timeouts = []
        self.quiet_for = 0.0
        self.after_quiet_bytes = b""
        self.stderr_every = 0.0
        self._quiet_until = None
        self._offsets = {1: 0, 2: 0}

    def resolve(self):
        if self._outcome is None:
            self._outcome = self._registry.handle(self.command, self)
        return self._outcome

    def take(self, index, size=-1):
        produced = self.resolve()[index]
        data = produced.encode() if isinstance(produced, str) else produced
        start = self._offsets[index]
        end = len(data) if size is None or size < 0 else min(len(data), start + size)
        self._offsets[index] = end
        return data[start:end]

    def next_line(self, index):
        produced = self.resolve()[index]
        data = produced.encode() if isinstance(produced, str) else produced
        start = self._offsets[index]
        end = data.find(b"\n", start)
        end = len(data) if end < 0 else end + 1
        self._offsets[index] = end
        return data[start:end]

    def after_quiet(self):
        if not self.quiet_for:
            return b""
        if self._quiet_until is None:
            self._quiet_until = time.monotonic() + self.quiet_for
        remaining = self._quiet_until - time.monotonic()
        wait = self.timeouts[-1] if self.timeouts and self.timeouts[-1] else remaining
        if wait < remaining:
            time.sleep(wait)
            raise socket.timeout()
        time.sleep(max(remaining, 0))
        self.quiet_for = 0.0
        return self.after_quiet_bytes

    @property
    def exit_status(self):
        return self.resolve()[0]


class FakeSSHClient:
    """Records what was asked of it; the sftp side operates on a real directory."""

    def __init__(self, registry):
        self._registry = registry
        self.connect_kwargs = None
        self.policy = None
        self.host_keys_loaded = None
        self.system_host_keys_loaded = False
        self.host_keys = FakeHostKeys()
        self.closed = False
        self.transport = FakeTransport(registry, FakeSocket())

    def get_host_keys(self):
        return self.host_keys

    def get_transport(self):
        return self.transport

    def load_host_keys(self, path):
        self.host_keys_loaded = path

    def load_system_host_keys(self):
        self.system_host_keys_loaded = True

    def set_missing_host_key_policy(self, policy):
        self.policy = policy

    def connect(self, **kwargs):
        self.connect_kwargs = kwargs
        self._registry.connections.append(kwargs)
        if self._registry.connect_error is not None:
            raise self._registry.connect_error
        presented = self._registry.presented_key
        if presented is None:
            return
        port = kwargs.get("port", 22)
        hostname = kwargs["hostname"]
        name = hostname if port == 22 else f"[{hostname}]:{port}"
        known = self.host_keys.get(name)
        if known is None:
            self.policy.missing_host_key(self, name, presented)
        elif presented not in known.values():
            raise BadHostKeyException(name, presented, next(iter(known.values())))

    def open_sftp(self):
        return FakeSFTP(self._registry.root)

    def exec_command(self, command, timeout=None, get_pty=False):
        session = FakeExec(self._registry, command)
        self._registry.commands.append(
            {"command": command, "timeout": timeout, "get_pty": get_pty}
        )
        self._registry.executions.append(session)
        return FakeStdin(session), FakeStdout(session, 1), FakeStdout(session, 2)

    def close(self):
        self.closed = True
        self.transport.close()


class FakeParamiko:
    """The module namespace `dbs.transports.ssh._paramiko()` is patched to return."""

    SSHException = SSHException
    AuthenticationException = AuthenticationException
    PasswordRequiredException = PasswordRequiredException
    BadHostKeyException = BadHostKeyException
    AutoAddPolicy = AutoAddPolicy
    RejectPolicy = RejectPolicy
    hostkeys = types.SimpleNamespace(HostKeyEntry=FakeHostKeyEntry)

    def __init__(self, root):
        self.root = root
        self.connections = []
        self.commands = []
        self.executions = []
        self.clients = []
        self.transports = []
        self.connect_error = None
        self.handshake_error = None
        self.presented_key = None
        self.dropped = False
        self.global_requests = []
        self.terminals = []
        self._handler = None

    def SSHClient(self):
        client = FakeSSHClient(self)
        self.clients.append(client)
        return client

    def Transport(self, sock):
        transport = FakeTransport(self, sock)
        self.transports.append(transport)
        return transport

    def on_exec(self, handler):
        self._handler = handler

    def handle(self, command, session):
        if self._handler is None:
            return 0, "", ""
        return self._handler(command, session)

    def remote_path(self, *parts):
        return os.path.join(self.root, *[p.lstrip("/") for p in parts])

    def make_remote_dir(self, remote_dir):
        os.makedirs(self.remote_path(remote_dir), exist_ok=True)
        return remote_dir

    def write_remote(self, remote_dir, name, data):
        os.makedirs(self.remote_path(remote_dir), exist_ok=True)
        with open(self.remote_path(remote_dir, name), "wb") as fh:
            fh.write(data)
        return posixpath.join(remote_dir, name)
