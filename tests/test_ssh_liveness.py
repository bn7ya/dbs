import io
import socket
import threading

import pytest

from dbs.exceptions import ConfigurationError, ConnectionLost, DBSError, RemoteTimeout
from dbs.naming import backup_filename
from dbs.transports import SSHTarget, open_session
from dbs.transports.ssh import (
    DEFAULT_COMMAND_TIMEOUT,
    DEFAULT_IO_TIMEOUT,
    DEFAULT_KEEPALIVE_INTERVAL,
    KEEPALIVE_REQUEST,
    SSHSession,
)

REMOTE_DIR = "/var/backups/app"


def target(**overrides):
    values = {"host": "h.example.com", "username": "deploy", "remote_dir": REMOTE_DIR}
    values.update(overrides)
    return SSHTarget(**values)


def test_a_target_keeps_the_connection_alive_and_bounds_commands_by_default():
    parsed = SSHTarget.from_dict({"host": "h.example.com", "username": "deploy"})

    assert parsed.keepalive_interval == DEFAULT_KEEPALIVE_INTERVAL == 15.0
    assert parsed.io_timeout == DEFAULT_IO_TIMEOUT
    assert parsed.command_timeout == DEFAULT_COMMAND_TIMEOUT


def test_a_target_reads_its_liveness_settings():
    parsed = SSHTarget.from_dict(
        {
            "host": "h",
            "username": "u",
            "keepalive_interval": 5,
            "io_timeout": "12",
            "command_timeout": 600,
        }
    )

    assert (parsed.keepalive_interval, parsed.io_timeout, parsed.command_timeout) == (
        5.0,
        12.0,
        600.0,
    )


@pytest.mark.parametrize(
    "setting",
    [{"keepalive_interval": -1}, {"io_timeout": 0}, {"command_timeout": 0}],
)
def test_a_target_refuses_liveness_settings_that_cannot_work(setting):
    with pytest.raises(ConfigurationError):
        target(**setting)


def test_a_connection_sends_keepalives_and_drops_when_nothing_answers(fake_ssh):
    with open_session(target(keepalive_interval=7, io_timeout=20)):
        pass

    transport = fake_ssh.clients[0].transport
    assert transport.keepalive == 7
    assert transport.sock.options[(socket.SOL_SOCKET, socket.SO_KEEPALIVE)] == 1
    if hasattr(socket, "TCP_USER_TIMEOUT"):
        assert transport.sock.options[(socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT)] == 20000


def test_sftp_reads_wait_no_longer_than_the_io_timeout(fake_ssh):
    fake_ssh.make_remote_dir(REMOTE_DIR)

    with open_session(target(io_timeout=9)) as session:
        session.names()
        assert session.sftp.get_channel().timeout == 9


def test_a_command_without_its_own_timeout_gets_the_targets(fake_ssh):
    with open_session(target(command_timeout=90)) as session:
        session.run("true")
        session.run("true", timeout=5)

    assert [command["timeout"] for command in fake_ssh.commands] == [90, 5]


def test_a_command_whose_connection_dropped_reports_the_loss(fake_ssh):
    def drop(command, session):
        fake_ssh.dropped = True
        return -1, "", ""

    fake_ssh.on_exec(drop)

    with open_session(target()) as session:
        with pytest.raises(ConnectionLost):
            session.run("python manage.py dbs_restore")
        assert session.is_alive() is False


def test_a_command_that_stops_answering_times_out(fake_ssh):
    def silent(command, session):
        raise socket.timeout("timed out")

    fake_ssh.on_exec(silent)

    with open_session(target()) as session:
        with pytest.raises(RemoteTimeout):
            session.run("sleep 600", timeout=1)


def test_a_failed_command_on_a_live_connection_is_a_plain_failure(fake_ssh):
    def broken(command, session):
        raise OSError("broken pipe")

    fake_ssh.on_exec(broken)

    with open_session(target()) as session:
        with pytest.raises(DBSError) as raised:
            session.run("true")

    assert not isinstance(raised.value, (ConnectionLost, RemoteTimeout))


def test_a_watched_session_reports_that_the_server_still_answers(fake_ssh):
    heard = threading.Event()
    beats = []

    def activity(moved):
        beats.append(moved)
        heard.set()

    session = SSHSession(target(keepalive_interval=0.01), on_activity=activity)
    with session:
        assert heard.wait(5)

    assert beats[0] == 0
    assert (KEEPALIVE_REQUEST, True) in fake_ssh.global_requests


def test_a_watched_session_stops_reporting_once_the_server_is_gone(fake_ssh):
    fake_ssh.dropped = True
    beats = []

    session = SSHSession(target(keepalive_interval=0.01), on_activity=beats.append)
    with session:
        session._ticker._thread.join(5)

    assert beats == []


def test_an_unwatched_session_starts_no_liveness_thread(fake_ssh):
    with open_session(target(keepalive_interval=0.01)) as session:
        assert session._ticker is None


def test_a_watched_session_counts_the_bytes_it_moves(fake_ssh, tmp_path):
    moved = []
    name = backup_filename()
    session = SSHSession(target(keepalive_interval=0), on_activity=moved.append)

    with session:
        session.push(b"x" * 300, name)
        session.pull(name)
        session.pull_to(name, str(tmp_path / "copy.dbs"))

    assert sum(moved) == 300 * 3


class Handle(io.BytesIO):
    def readv(self, chunks):
        for offset, size in chunks:
            self.seek(offset)
            yield self.read(size)


class Opening:
    def __init__(self, handle):
        self.handle = handle

    def open(self, path, mode="r"):
        return self.handle


def test_the_upgrade_names_targets_that_rely_on_the_default_command_limit(settings):
    from dbs import upgrade

    settings.DBS_SSH_TARGETS = {
        "nightly": {"host": "h", "username": "u"},
        "archive": {"host": "h", "username": "u", "command_timeout": 86400},
    }

    finding = upgrade.RemoteCommandLimits().check()

    assert finding.level == upgrade.OK
    assert "nightly" in finding.message and "archive" not in finding.message
    assert "6 hours" in finding.message
    settings.DBS_SSH_TARGETS = {}
    assert upgrade.RemoteCommandLimits().check().message == "no SSH targets are configured"


def test_files_opened_on_a_metered_channel_count_reads_windows_and_writes():
    from dbs.transports.ssh import _MeteredSFTP

    moved = []
    handle = Handle(b"abcdefgh")
    sftp = _MeteredSFTP(Opening(handle), moved.append)

    with sftp.open("/srv/app/data.bin", "rb") as opened:
        assert opened.read(3) == b"abc"
        assert list(opened.readv([(3, 2), (5, 3)])) == [b"de", b"fgh"]
        opened.write(b"ij")

    assert moved == [3, 2, 3, 2]
    assert handle.closed
