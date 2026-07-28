"""A paramiko stand-in backed by a real directory, so transports test without a server."""

import errno
import io
import os
import posixpath


class SSHException(Exception):
    pass


class AuthenticationException(SSHException):
    pass


class AutoAddPolicy:
    pass


class RejectPolicy:
    pass


class FakeAttr:
    def __init__(self, filename, st_size, st_mtime):
        self.filename = filename
        self.st_size = st_size
        self.st_mtime = st_mtime


class FakeSFTP:
    def __init__(self, root):
        self.root = root

    def _local(self, remote_path):
        return os.path.join(self.root, remote_path.lstrip("/"))

    def _missing(self, remote_path):
        return FileNotFoundError(
            errno.ENOENT, "No such file", remote_path
        )

    def putfo(self, handle, remote_path):
        local = self._local(remote_path)
        if not os.path.isdir(os.path.dirname(local)):
            raise self._missing(remote_path)
        with open(local, "wb") as fh:
            fh.write(handle.read())

    def getfo(self, remote_path, handle):
        local = self._local(remote_path)
        if not os.path.exists(local):
            raise self._missing(remote_path)
        with open(local, "rb") as fh:
            handle.write(fh.read())

    def get(self, remote_path, local_path):
        local = self._local(remote_path)
        if not os.path.exists(local):
            raise self._missing(remote_path)
        with open(local, "rb") as source, open(local_path, "wb") as target:
            target.write(source.read())

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

    def rename(self, source, destination):
        os.replace(self._local(source), self._local(destination))


class FakeChannel:
    def __init__(self, session):
        self._session = session

    def shutdown_write(self):
        self._session.stdin_closed = True

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
        return self._session.resolve()[self._index].encode()


class FakeExec:
    def __init__(self, registry, command):
        self._registry = registry
        self._outcome = None
        self.command = command
        self.stdin = ""
        self.stdin_closed = False

    def resolve(self):
        if self._outcome is None:
            self._outcome = self._registry.handle(self.command, self)
        return self._outcome

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
        self.closed = False

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


class FakeParamiko:
    """The module namespace `dbs.transports.ssh._paramiko()` is patched to return."""

    SSHException = SSHException
    AuthenticationException = AuthenticationException
    AutoAddPolicy = AutoAddPolicy
    RejectPolicy = RejectPolicy

    def __init__(self, root):
        self.root = root
        self.connections = []
        self.commands = []
        self.executions = []
        self.clients = []
        self.connect_error = None
        self._handler = None

    def SSHClient(self):
        client = FakeSSHClient(self)
        self.clients.append(client)
        return client

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
