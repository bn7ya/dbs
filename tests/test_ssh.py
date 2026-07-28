"""SSH transport: target configuration, auth wiring, and session operations."""

import os

import pytest
from django.test import override_settings

from dbs.exceptions import ConfigurationError, DBSError
from dbs.naming import backup_filename
from dbs.transports import SSHTarget, open_session
from dbs.transports.ssh import (
    check_connection,
    delete_backup,
    list_backup_details,
    list_backups,
    pull_backup,
    pull_backup_to,
    push_backup,
)
from tests.fake_ssh import AutoAddPolicy, RejectPolicy

REMOTE_DIR = "/var/backups/app"


def target(**overrides):
    values = {
        "host": "h.example.com",
        "username": "deploy",
        "remote_dir": REMOTE_DIR,
    }
    values.update(overrides)
    return SSHTarget(**values)


def test_from_dict_defaults_and_security_posture():
    parsed = SSHTarget.from_dict({"host": "h.example.com", "username": "deploy"})
    assert parsed.port == 22
    assert parsed.remote_dir == "."
    assert parsed.connect_timeout == 30.0
    # Fail-closed by default: unknown host keys are rejected, not auto-added.
    assert parsed.auto_add_host_key is False
    assert parsed.host_key_policy == "reject-unknown"


def test_from_dict_missing_required_key():
    with pytest.raises(ConfigurationError):
        SSHTarget.from_dict({"host": "only-host"})


def test_from_dict_rejects_unknown_keys():
    with pytest.raises(ConfigurationError) as excinfo:
        SSHTarget.from_dict(
            {"host": "h", "username": "u", "known_host": "/tmp/known_hosts"}
        )
    assert "known_host" in str(excinfo.value)


def test_user_and_key_file_aliases():
    parsed = SSHTarget.from_dict(
        {"host": "h", "user": "deploy", "key_file": "/keys/id_ed25519"}
    )
    assert parsed.username == "deploy"
    assert parsed.key_filename == "/keys/id_ed25519"


def test_home_relative_paths_are_expanded():
    parsed = SSHTarget.from_dict(
        {
            "host": "h",
            "username": "u",
            "key_file": "~/keys/prod.pem",
            "known_hosts": "~/.ssh/known_hosts",
        }
    )
    assert parsed.key_filename == os.path.expanduser("~/keys/prod.pem")
    assert parsed.known_hosts == os.path.expanduser("~/.ssh/known_hosts")


def test_secrets_can_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("DBS_TEST_SSH_PASSWORD", "from-env")
    monkeypatch.setenv("DBS_TEST_KEY_PASSPHRASE", "key-secret")
    parsed = SSHTarget.from_dict(
        {
            "host": "h",
            "username": "u",
            "password_env": "DBS_TEST_SSH_PASSWORD",
            "key_passphrase_env": "DBS_TEST_KEY_PASSPHRASE",
        }
    )
    assert parsed.password == "from-env"
    assert parsed.key_passphrase == "key-secret"


def test_missing_environment_secret_is_reported():
    with pytest.raises(ConfigurationError):
        SSHTarget.from_dict(
            {"host": "h", "username": "u", "password_env": "DBS_ABSENT_VARIABLE"}
        )


def test_a_target_with_no_authentication_method_is_refused():
    with pytest.raises(ConfigurationError):
        SSHTarget(host="h", username="u", use_agent=False)


@override_settings(
    DBS_SSH_TARGETS={
        "offsite": {
            "host": "backups.example.com",
            "username": "deploy",
            "key_filename": "/keys/id_ed25519",
            "remote_dir": "/var/backups/app",
        }
    }
)
def test_from_settings():
    parsed = SSHTarget.from_settings("offsite")
    assert parsed.host == "backups.example.com"
    assert parsed.remote_dir == "/var/backups/app"
    with pytest.raises(ConfigurationError):
        SSHTarget.from_settings("missing")


def test_missing_paramiko_names_the_extra(monkeypatch):
    import dbs.transports.ssh as ssh_module

    monkeypatch.delattr("dbs.transports.ssh._paramiko")

    def explode():
        raise ImportError("no paramiko")

    monkeypatch.setattr(ssh_module, "_paramiko", explode, raising=False)
    with pytest.raises(ImportError):
        ssh_module._paramiko()


def test_connect_passes_auth_and_timeouts(fake_ssh):
    fake_ssh.make_remote_dir(REMOTE_DIR)
    with open_session(
        target(key_filename="/keys/prod.pem", key_passphrase="secret", connect_timeout=5)
    ) as session:
        session.names()

    kwargs = fake_ssh.connections[0]
    assert kwargs["key_filename"] == "/keys/prod.pem"
    assert kwargs["passphrase"] == "secret"
    assert kwargs["timeout"] == 5
    assert kwargs["auth_timeout"] == 5
    assert kwargs["look_for_keys"] is False
    assert isinstance(fake_ssh.clients[0].policy, RejectPolicy)


def test_auto_add_host_key_selects_the_permissive_policy(fake_ssh):
    fake_ssh.make_remote_dir(REMOTE_DIR)
    with open_session(target(auto_add_host_key=True)) as session:
        session.names()
    assert isinstance(fake_ssh.clients[0].policy, AutoAddPolicy)


def test_push_creates_the_directory_and_lands_atomically(fake_ssh):
    remote_path = push_backup(b"payload", backup_filename(), target())

    assert remote_path.startswith(REMOTE_DIR)
    listed = list_backups(target())
    assert len(listed) == 1
    assert not any(name.endswith(".part") for name in os.listdir(fake_ssh.remote_path(REMOTE_DIR)))
    assert pull_backup(listed[0], target()) == b"payload"


def test_listing_ignores_files_that_are_not_backups(fake_ssh):
    name = backup_filename()
    fake_ssh.write_remote(REMOTE_DIR, name, b"payload")
    fake_ssh.write_remote(REMOTE_DIR, "notes.txt", b"hello")

    assert list_backups(target()) == [name]
    assert list_backups(target(), pattern_only=False) == sorted([name, "notes.txt"])


def test_details_report_size_and_time(fake_ssh):
    name = backup_filename()
    fake_ssh.write_remote(REMOTE_DIR, name, b"1234567890")

    details = list_backup_details(target())

    assert [detail.name for detail in details] == [name]
    assert details[0].size == 10
    assert details[0].modified is not None


def test_pull_to_streams_to_disk_and_leaves_no_partial(fake_ssh, tmp_path):
    name = backup_filename()
    fake_ssh.write_remote(REMOTE_DIR, name, b"payload")
    destination = tmp_path / "local.dbs"

    assert pull_backup_to(name, str(destination), target()) == 7
    assert destination.read_bytes() == b"payload"
    assert not (tmp_path / "local.dbs.part").exists()


def test_a_failed_pull_does_not_clobber_an_existing_file(fake_ssh, tmp_path):
    fake_ssh.make_remote_dir(REMOTE_DIR)
    destination = tmp_path / "local.dbs"
    destination.write_bytes(b"previous")

    with pytest.raises(DBSError):
        pull_backup_to(backup_filename(), str(destination), target())

    assert destination.read_bytes() == b"previous"
    assert not (tmp_path / "local.dbs.part").exists()


def test_delete_removes_the_remote_file(fake_ssh):
    name = backup_filename()
    fake_ssh.write_remote(REMOTE_DIR, name, b"payload")

    delete_backup(name, target())

    assert list_backups(target()) == []
    with pytest.raises(DBSError):
        delete_backup(name, target())


def test_run_captures_status_and_streams(fake_ssh):
    fake_ssh.on_exec(lambda command, session: (3, "out", "boom"))
    fake_ssh.make_remote_dir(REMOTE_DIR)

    with open_session(target()) as session:
        result = session.run("false", stdin_line="secret")

    assert (result.exit_status, result.stdout, result.stderr) == (3, "out", "boom")
    assert result.ok is False
    assert fake_ssh.executions[0].stdin == "secret\n"
    assert fake_ssh.executions[0].stdin_closed is True
    assert fake_ssh.commands[0]["get_pty"] is False


def test_check_connection_reports_the_facts(fake_ssh):
    fake_ssh.on_exec(lambda command, session: (0, "Linux 6.1\n", ""))
    name = backup_filename()
    fake_ssh.write_remote(REMOTE_DIR, name, b"payload")

    facts = check_connection(target())

    assert facts["system"] == "Linux 6.1"
    assert facts["host_key_policy"] == "reject-unknown"
    assert facts["remote_dir"] == REMOTE_DIR
    assert facts["backups"] == 1
