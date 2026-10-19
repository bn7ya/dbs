"""The SSH transport against a real OpenSSH server, when DBS_TEST_SSH_HOST names one."""

import hashlib
import io
import os
import stat
import uuid

import pytest

pytest.importorskip("paramiko")

from dbs.engine import create_backup, validate_backup  # noqa: E402
from dbs.exceptions import ConfigurationError, DBSError, HostKeyError  # noqa: E402
from dbs.naming import backup_filename  # noqa: E402
from dbs.transports import SSHTarget, fetch_host_key, open_session  # noqa: E402
from tests.conftest import FAST_KDF  # noqa: E402

HOST = os.environ.get("DBS_TEST_SSH_HOST", "")
PORT = int(os.environ.get("DBS_TEST_SSH_PORT", "22"))
USER = os.environ.get("DBS_TEST_SSH_USER", "")
KEY = os.environ.get("DBS_TEST_SSH_KEY", "")
PASSWORD = os.environ.get("DBS_TEST_SSH_PASSWORD", "")
KNOWN_HOSTS = os.environ.get("DBS_TEST_SSH_KNOWN_HOSTS", "")
PASSPHRASE = "openssh-live-passphrase"

CONFIGURED = bool(HOST and USER and KEY and KNOWN_HOSTS)
SETUP = "Set DBS_TEST_SSH_HOST, _PORT, _USER, _KEY and _KNOWN_HOSTS to an OpenSSH server."

if os.environ.get("DBS_TEST_SSH_REQUIRED") and not CONFIGURED:
    pytest.fail(f"DBS_TEST_SSH_REQUIRED is set. {SETUP}", pytrace=False)

pytestmark = pytest.mark.skipif(not CONFIGURED, reason=SETUP)


@pytest.fixture
def remote_dir():
    return f"/tmp/dbs-openssh-{uuid.uuid4().hex}"


def target(**overrides):
    values = {
        "host": HOST,
        "port": PORT,
        "username": USER,
        "key_filename": KEY,
        "known_hosts": KNOWN_HOSTS,
        "use_agent": False,
        "connect_timeout": 15,
    }
    values.update(overrides)
    return SSHTarget(**values)


def remote_mode(session, path):
    return stat.S_IMODE(session.sftp.stat(path).st_mode)


def test_a_key_authenticates_and_runs_a_command():
    with open_session(target()) as session:
        result = session.run("echo dbs-over-openssh")

    assert result.ok
    assert result.stdout.strip() == "dbs-over-openssh"


@pytest.mark.skipif(not PASSWORD, reason="Set DBS_TEST_SSH_PASSWORD to test password logins.")
def test_a_password_authenticates():
    with open_session(target(key_filename=None, password=PASSWORD)) as session:
        result = session.run("id -un")

    assert result.stdout.strip() == USER


def test_a_wrong_password_is_refused():
    with pytest.raises(ConfigurationError, match="authentication failed"):
        with open_session(target(key_filename=None, password="not-the-password")) as session:
            session.run("true")


def test_the_fetched_host_key_is_the_one_known_hosts_trusts():
    key = fetch_host_key(HOST, PORT, timeout=15)

    with open(KNOWN_HOSTS, encoding="ascii") as fh:
        trusted = {" ".join(line.split()[1:3]) for line in fh if line.strip()}
    assert key.line in trusted

    with open_session(target(known_hosts=None, host_key=key.line)) as session:
        assert session.run("true").ok


def test_a_server_missing_from_known_hosts_is_refused(tmp_path):
    empty = tmp_path / "known_hosts"
    empty.write_text("")

    with pytest.raises(HostKeyError):
        with open_session(target(known_hosts=str(empty))) as session:
            session.run("true")


def test_a_different_pinned_key_is_refused():
    import paramiko

    impostor = paramiko.ECDSAKey.generate()

    with pytest.raises(HostKeyError, match="does not match"):
        with open_session(
            target(known_hosts=None, host_key=f"{impostor.get_name()} {impostor.get_base64()}")
        ) as session:
            session.run("true")


def test_a_passphrase_line_arrives_on_standard_input():
    with open_session(target()) as session:
        result = session.run("head -n 1 | sha256sum", stdin_line=PASSPHRASE)

    expected = hashlib.sha256((PASSPHRASE + "\n").encode()).hexdigest()
    assert result.stdout.split()[0] == expected


def test_a_fed_file_arrives_whole_after_its_first_line():
    payload = os.urandom(3 * 1024 * 1024 + 17)

    with open_session(target()) as session:
        result = session.feed(
            "read line && printf '%s ' \"$line\" && sha256sum",
            io.BytesIO(payload),
            stdin_line="first",
        )

    assert result.ok
    assert result.stdout.split() == ["first", hashlib.sha256(payload).hexdigest(), "-"]


def test_a_command_that_never_exits_is_stopped_at_its_timeout():
    with open_session(target()) as session:
        with pytest.raises(DBSError, match="timed out after 1"):
            session.run("sleep 30", timeout=1)


@pytest.mark.django_db
def test_a_backup_travels_both_ways_and_stays_private(remote_dir, tmp_path):
    container = create_backup(PASSPHRASE, kdf_params=FAST_KDF)
    name = backup_filename("openssh")
    local = tmp_path / name
    try:
        with open_session(target(remote_dir=remote_dir)) as session:
            remote_path = session.push(container, name)
            assert session.names() == [name]
            assert remote_mode(session, remote_path) == 0o600
            assert not [entry for entry in session.names(pattern_only=False) if entry.endswith(".part")]

            assert session.pull(name) == container
            assert session.pull_to(name, str(local)) == len(container)
            details = session.details()
    finally:
        with open_session(target()) as session:
            session.run(f"rm -rf {remote_dir}")

    assert stat.S_IMODE(local.stat().st_mode) == 0o600
    assert local.read_bytes() == container
    assert [detail.size for detail in details] == [len(container)]
    assert validate_backup(local.read_bytes(), PASSPHRASE).ok


def test_delete_removes_a_pushed_backup(remote_dir):
    name = backup_filename("openssh")
    try:
        with open_session(target(remote_dir=remote_dir)) as session:
            session.push(b"payload", name)
            session.delete(name)
            assert session.names() == []
    finally:
        with open_session(target()) as session:
            session.run(f"rm -rf {remote_dir}")
