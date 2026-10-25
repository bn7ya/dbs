"""Each failure a developer can expect raises an exception that names it."""

import pytest

from dbs import create_backup, exceptions, jobs, schedule_runner, write_backup
from dbs.exceptions import (
    AuthenticationFailed,
    ConfigurationError,
    DBSError,
    HostUnreachable,
)
from dbs.transports import SSHTarget, fetch_host_key, open_session
from dbs.transports import ssh
from tests.conftest import FAST_KDF
from tests.fake_ssh import AuthenticationException


@pytest.mark.parametrize("passphrase", ["", None])
def test_a_backup_without_a_passphrase_is_refused_before_anything_is_written(
    db, tmp_path, passphrase
):
    output = tmp_path / "open-to-anyone.dbs"

    with pytest.raises(ConfigurationError, match="needs a passphrase"):
        write_backup(str(output), passphrase, kdf_params=FAST_KDF)
    with pytest.raises(ConfigurationError, match="needs a passphrase"):
        create_backup(passphrase, kdf_params=FAST_KDF)

    assert list(tmp_path.iterdir()) == []


def test_an_ssh_host_that_cannot_be_reached_says_so(fake_ssh, monkeypatch):
    def refuse(address, timeout):
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr("dbs.transports.ssh.socket.create_connection", refuse)
    fake_ssh.connect_error = ConnectionRefusedError("refused")

    with pytest.raises(HostUnreachable, match="Cannot reach h.example.com:22"):
        fetch_host_key("h.example.com")
    with pytest.raises(HostUnreachable, match="Cannot reach h.example.com:22"):
        open_session(SSHTarget(host="h.example.com", username="deploy")).__enter__()


def test_ssh_credentials_the_server_refuses_say_so(fake_ssh):
    fake_ssh.connect_error = AuthenticationException("no")

    with pytest.raises(AuthenticationFailed, match="deploy@h.example.com"):
        open_session(SSHTarget(host="h.example.com", username="deploy")).__enter__()


def test_every_exception_dbs_raises_lives_in_one_module_and_is_a_dbs_error():
    assert jobs.Busy is exceptions.Busy
    assert schedule_runner.ScheduleError is exceptions.ScheduleError
    assert ssh.StreamInterrupted is exceptions.StreamInterrupted
    assert issubclass(AuthenticationFailed, ConfigurationError)
    assert issubclass(HostUnreachable, DBSError)
    raised = [
        value
        for value in vars(exceptions).values()
        if isinstance(value, type) and issubclass(value, Exception)
    ]
    assert all(issubclass(kind, DBSError) for kind in raised)
