"""A real SSH handshake over loopback: auth wiring and the stdin passphrase channel."""

import base64
import socket
import threading

import pytest

paramiko = pytest.importorskip("paramiko")

from dbs.client.config import ServerProfile  # noqa: E402
from dbs.client.remote import trigger_remote_backup  # noqa: E402
from dbs.exceptions import ConfigurationError  # noqa: E402
from dbs.transports.ssh import SSHTarget, open_session  # noqa: E402

PASSWORD = "login-secret"
PASSPHRASE = "backup-pass-phrase"


class Handler(paramiko.ServerInterface):
    def __init__(self, record, authorized_key):
        self.record = record
        self.authorized_key = authorized_key
        self.exec_ready = threading.Event()

    def get_allowed_auths(self, username):
        return "password,publickey"

    def check_auth_password(self, username, password):
        self.record["username"] = username
        if password == PASSWORD:
            self.record["auth"] = "password"
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def check_auth_publickey(self, username, key):
        self.record["username"] = username
        if self.authorized_key is not None and key == self.authorized_key:
            self.record["auth"] = "publickey"
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def check_channel_request(self, kind, chanid):
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_exec_request(self, channel, command):
        self.record["command"] = command.decode()
        self.record["channel"] = channel
        self.exec_ready.set()
        return True


class LoopbackServer:
    def __init__(self, host_key, authorized_key):
        self.host_key = host_key
        self.authorized_key = authorized_key
        self.record = {}
        self._socket = socket.socket()
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(1)
        self.port = self._socket.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        try:
            connection, _ = self._socket.accept()
        except OSError:
            return
        transport = paramiko.Transport(connection)
        transport.add_server_key(self.host_key)
        handler = Handler(self.record, self.authorized_key)
        try:
            transport.start_server(server=handler)
            channel = transport.accept(10)
            if channel is None:
                return
            if handler.exec_ready.wait(10):
                self.record["stdin"] = channel.makefile("r").readline()
                channel.sendall(b"served\n")
                channel.send_exit_status(0)
            channel.close()
        except Exception:
            pass
        finally:
            transport.close()
            connection.close()

    def close(self):
        try:
            self._socket.close()
        except OSError:
            pass


@pytest.fixture
def host_key():
    return paramiko.RSAKey.generate(2048)


@pytest.fixture
def client_key():
    return paramiko.RSAKey.generate(2048)


def known_hosts_file(tmp_path, port, host_key):
    path = tmp_path / "known_hosts"
    encoded = base64.b64encode(host_key.asbytes()).decode()
    path.write_text(f"[127.0.0.1]:{port} {host_key.get_name()} {encoded}\n")
    return str(path)


def test_password_authentication_over_a_real_handshake(tmp_path, host_key):
    server = LoopbackServer(host_key, authorized_key=None)
    try:
        target = SSHTarget(
            host="127.0.0.1",
            port=server.port,
            username="deploy",
            password=PASSWORD,
            use_agent=False,
            known_hosts=known_hosts_file(tmp_path, server.port, host_key),
            connect_timeout=10,
        )
        with open_session(target) as session:
            result = session.run("echo hello")
        assert result.exit_status == 0
        assert result.stdout.strip() == "served"
    finally:
        server.close()

    assert server.record["auth"] == "password"
    assert server.record["username"] == "deploy"


def test_private_key_authentication_over_a_real_handshake(
    tmp_path, host_key, client_key
):
    key_path = tmp_path / "id_rsa"
    client_key.write_private_key_file(str(key_path))
    server = LoopbackServer(host_key, authorized_key=client_key)
    try:
        target = SSHTarget(
            host="127.0.0.1",
            port=server.port,
            username="deploy",
            key_filename=str(key_path),
            use_agent=False,
            known_hosts=known_hosts_file(tmp_path, server.port, host_key),
            connect_timeout=10,
        )
        with open_session(target) as session:
            session.run("true")
    finally:
        server.close()

    assert server.record["auth"] == "publickey"


def test_an_encrypted_key_is_unlocked_with_its_passphrase(
    tmp_path, host_key, client_key
):
    key_path = tmp_path / "encrypted.pem"
    client_key.write_private_key_file(str(key_path), password="key-secret")
    server = LoopbackServer(host_key, authorized_key=client_key)
    try:
        target = SSHTarget(
            host="127.0.0.1",
            port=server.port,
            username="deploy",
            key_filename=str(key_path),
            key_passphrase="key-secret",
            use_agent=False,
            known_hosts=known_hosts_file(tmp_path, server.port, host_key),
            connect_timeout=10,
        )
        with open_session(target) as session:
            session.run("true")
    finally:
        server.close()

    assert server.record["auth"] == "publickey"


def test_a_wrong_key_passphrase_is_reported_clearly(tmp_path, host_key, client_key):
    key_path = tmp_path / "encrypted.pem"
    client_key.write_private_key_file(str(key_path), password="key-secret")
    server = LoopbackServer(host_key, authorized_key=client_key)
    try:
        target = SSHTarget(
            host="127.0.0.1",
            port=server.port,
            username="deploy",
            key_filename=str(key_path),
            key_passphrase="wrong",
            use_agent=False,
            known_hosts=known_hosts_file(tmp_path, server.port, host_key),
            connect_timeout=10,
        )
        with pytest.raises(ConfigurationError):
            with open_session(target) as session:
                session.run("true")
    finally:
        server.close()


def test_an_unknown_host_key_is_rejected(tmp_path, host_key):
    server = LoopbackServer(host_key, authorized_key=None)
    try:
        target = SSHTarget(
            host="127.0.0.1",
            port=server.port,
            username="deploy",
            password=PASSWORD,
            use_agent=False,
            known_hosts=str(tmp_path / "empty_known_hosts"),
            connect_timeout=10,
        )
        (tmp_path / "empty_known_hosts").write_text("")
        with pytest.raises(Exception):
            with open_session(target) as session:
                session.run("true")
    finally:
        server.close()


def test_the_passphrase_reaches_the_server_on_stdin_not_in_argv(tmp_path, host_key):
    server = LoopbackServer(host_key, authorized_key=None)
    profile = ServerProfile(
        name="live",
        host="127.0.0.1",
        port=server.port,
        username="deploy",
        password=PASSWORD,
        use_agent=False,
        known_hosts=known_hosts_file(tmp_path, server.port, host_key),
        connect_timeout=10,
        remote_dir="/tmp/dbs-live",
        project_dir="/srv/app",
        python="/srv/app/.venv/bin/python",
    )
    try:
        with open_session(profile.ssh_target()) as session:
            session.ensure_dir = lambda: profile.remote_dir
            trigger_remote_backup(session, profile, PASSPHRASE, "live.dbs")
    finally:
        server.close()

    assert server.record["stdin"] == PASSPHRASE + "\n"
    assert PASSPHRASE not in server.record["command"]
    assert "--passphrase-stdin" in server.record["command"]
