import io
import os
import socket
import threading
import time

import pytest

paramiko = pytest.importorskip("paramiko")

from dbs.transports.ssh import SSHTarget, StreamInterrupted, open_session  # noqa: E402
from tests.test_ssh_live import PASSWORD, Handler, known_hosts_file  # noqa: E402

PAYLOAD = os.urandom(3 * 1024 * 1024 + 11)


class StreamingServer:
    def __init__(self, host_key, *, payload=PAYLOAD, stderr=b"", ending="exit"):
        self.host_key = host_key
        self.payload = payload
        self.stderr = stderr
        self.ending = ending
        self.record = {}
        self.released = threading.Event()
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
        handler = Handler(self.record, None)
        try:
            transport.start_server(server=handler)
            channel = transport.accept(10)
            if channel is None or not handler.exec_ready.wait(10):
                return
            self.record["stdin"] = channel.makefile("r").readline()
            if self.stderr:
                channel.sendall_stderr(self.stderr)
            if self.ending == "drop":
                channel.sendall(self.payload[: len(self.payload) // 2])
                transport.close()
                return
            channel.sendall(self.payload)
            if self.ending == "hang":
                self.released.wait(30)
            channel.send_exit_status(0)
            channel.close()
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


def target_for(tmp_path, server, host_key):
    return SSHTarget(
        host="127.0.0.1",
        port=server.port,
        username="deploy",
        password=PASSWORD,
        use_agent=False,
        known_hosts=known_hosts_file(tmp_path, server.port, host_key),
        connect_timeout=10,
    )


def test_a_large_stdout_arrives_whole_with_stderr_beside_it(tmp_path, host_key):
    server = StreamingServer(host_key, stderr=b'working\n{"name": "web.dbs"}\n')
    received = io.BytesIO()
    progress = []
    try:
        with open_session(target_for(tmp_path, server, host_key)) as session:
            result = session.stream(
                "dbs backup --stream",
                received,
                stdin_line="secret",
                timeout=30,
                progress=progress.append,
            )
    finally:
        server.close()

    assert result.exit_status == 0
    assert received.getvalue() == PAYLOAD
    assert result.stderr.splitlines()[-1] == '{"name": "web.dbs"}'
    assert progress[-1] == len(PAYLOAD)
    assert progress == sorted(progress)
    assert server.record["stdin"] == "secret\n"


def test_a_connection_lost_mid_stream_is_interrupted(tmp_path, host_key):
    server = StreamingServer(host_key, ending="drop")
    received = io.BytesIO()
    try:
        with open_session(target_for(tmp_path, server, host_key)) as session:
            with pytest.raises(StreamInterrupted):
                session.stream("dbs backup --stream", received, timeout=30)
    finally:
        server.close()

    assert len(received.getvalue()) < len(PAYLOAD)


def test_a_stream_that_outlives_its_timeout_is_interrupted(tmp_path, host_key):
    server = StreamingServer(host_key, payload=b"partial", ending="hang")
    try:
        with open_session(target_for(tmp_path, server, host_key)) as session:
            started = time.monotonic()
            with pytest.raises(StreamInterrupted, match="timed out after 1"):
                session.stream("dbs backup --stream", io.BytesIO(), timeout=1)
            elapsed = time.monotonic() - started
    finally:
        server.close()

    assert elapsed < 5
