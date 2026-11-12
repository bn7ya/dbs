"""A real SSH handshake over loopback: auth wiring and the stdin passphrase channel."""

import base64
import io
import socket
import threading
import time

import pytest

paramiko = pytest.importorskip("paramiko")

from dbs.exceptions import ConfigurationError, DBSError, HostKeyError  # noqa: E402
from dbs.transports.ssh import (  # noqa: E402
    HostKey,
    SSHTarget,
    fetch_host_key,
    open_session,
)

PASSWORD = "login-secret"
PASSPHRASE = "backup-pass-phrase"
WINDOW_AND_HALF = 3 * 1024 * 1024
HANG_UP_WAIT = 10


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
    def __init__(
        self,
        host_key,
        authorized_key,
        *,
        exits=True,
        prints=b"served\n",
        complains=b"",
    ):
        self.host_key = host_key
        self.authorized_key = authorized_key
        self.exits = exits
        self.prints = prints
        self.complains = complains
        self.released = threading.Event()
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
                channel.sendall(self.prints)
                channel.sendall_stderr(self.complains)
                if not self.exits:
                    self.released.wait(30)
                channel.send_exit_status(0)
            channel.close()
            transport.join(HANG_UP_WAIT)
        except Exception:
            pass
        finally:
            transport.close()
            connection.close()

    def close(self):
        self.released.set()
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
        with pytest.raises(HostKeyError):
            with open_session(target) as session:
                session.run("true")
    finally:
        server.close()


def test_fetch_host_key_reads_the_key_a_real_server_presents(host_key):
    server = LoopbackServer(host_key, authorized_key=None)
    try:
        key = fetch_host_key("127.0.0.1", server.port, timeout=10)
    finally:
        server.close()

    assert key.line == f"{host_key.get_name()} {host_key.get_base64()}"
    assert key.fingerprint == host_key.fingerprint


def test_a_pinned_host_key_and_an_in_memory_key_over_a_real_handshake(
    host_key, client_key
):
    private_key = io.StringIO()
    client_key.write_private_key(private_key, password="key-secret")
    server = LoopbackServer(host_key, authorized_key=client_key)
    try:
        target = SSHTarget(
            host="127.0.0.1",
            port=server.port,
            username="deploy",
            private_key=private_key.getvalue(),
            key_passphrase="key-secret",
            host_key=HostKey(host_key.get_name(), host_key.get_base64()).line,
            use_agent=False,
            connect_timeout=10,
        )
        with open_session(target) as session:
            session.run("true")
    finally:
        server.close()

    assert server.record["auth"] == "publickey"


def test_a_different_pinned_key_is_refused_over_a_real_handshake(host_key):
    impostor = paramiko.RSAKey.generate(2048)
    server = LoopbackServer(host_key, authorized_key=None)
    try:
        target = SSHTarget(
            host="127.0.0.1",
            port=server.port,
            username="deploy",
            password=PASSWORD,
            host_key=f"{impostor.get_name()} {impostor.get_base64()}",
            use_agent=False,
            connect_timeout=10,
        )
        with pytest.raises(HostKeyError, match="does not match"):
            with open_session(target) as session:
                session.run("true")
    finally:
        server.close()


def test_the_passphrase_reaches_the_server_on_stdin_not_in_argv(tmp_path, host_key):
    server = LoopbackServer(host_key, authorized_key=None)
    target = SSHTarget(
        host="127.0.0.1",
        port=server.port,
        username="deploy",
        password=PASSWORD,
        use_agent=False,
        known_hosts=known_hosts_file(tmp_path, server.port, host_key),
        connect_timeout=10,
    )
    received = io.BytesIO()
    try:
        with open_session(target) as session:
            result = session.stream(
                "python manage.py dbs backup --stream --passphrase-stdin",
                received,
                stdin_line=PASSPHRASE,
            )
    finally:
        server.close()

    assert result.exit_status == 0
    assert received.getvalue() == b"served\n"
    assert server.record["stdin"] == PASSPHRASE + "\n"
    assert PASSPHRASE not in server.record["command"]
    assert "--passphrase-stdin" in server.record["command"]


def password_target(server, tmp_path, host_key):
    return SSHTarget(
        host="127.0.0.1",
        port=server.port,
        username="deploy",
        password=PASSWORD,
        use_agent=False,
        known_hosts=known_hosts_file(tmp_path, server.port, host_key),
        connect_timeout=10,
    )


def test_a_command_that_prints_more_than_the_channel_window_is_read_whole(
    tmp_path, host_key
):
    printed = b"x" * WINDOW_AND_HALF
    server = LoopbackServer(host_key, authorized_key=None, prints=printed)
    try:
        with open_session(password_target(server, tmp_path, host_key)) as session:
            result = session.run("docker inspect", timeout=30)
    finally:
        server.close()

    assert result.exit_status == 0
    assert result.stdout == printed.decode()
    assert result.stdout_truncated is False


def test_standard_error_longer_than_the_channel_window_does_not_stall_a_command(
    tmp_path, host_key
):
    complaint = b"e" * WINDOW_AND_HALF
    server = LoopbackServer(host_key, authorized_key=None, complains=complaint)
    try:
        with open_session(password_target(server, tmp_path, host_key)) as session:
            result = session.run("docker compose build", timeout=30)
    finally:
        server.close()

    assert result.exit_status == 0
    assert result.stdout == "served\n"
    assert result.stderr == complaint.decode()


def test_output_past_the_bound_is_read_to_its_end_and_cut(
    tmp_path, host_key, monkeypatch
):
    monkeypatch.setattr("dbs.transports.ssh.MAX_COMMAND_OUTPUT", 1024 * 1024)
    server = LoopbackServer(
        host_key, authorized_key=None, prints=b"a" * 1024 * 1024 + b"b" * WINDOW_AND_HALF
    )
    try:
        with open_session(password_target(server, tmp_path, host_key)) as session:
            result = session.run("docker inspect", timeout=30)
    finally:
        server.close()

    assert result.exit_status == 0
    assert result.stdout == "a" * 1024 * 1024
    assert result.stdout_truncated is True


def test_a_command_that_never_exits_is_stopped_at_its_timeout(tmp_path, host_key):
    server = LoopbackServer(host_key, authorized_key=None, exits=False)
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
            started = time.monotonic()
            with pytest.raises(DBSError, match="timed out after 1"):
                session.run("sleep forever", timeout=1)
            elapsed = time.monotonic() - started
    finally:
        server.close()

    assert elapsed < 5
