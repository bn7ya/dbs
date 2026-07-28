"""How the client asks a server for a backup, and where the passphrase travels."""

import pytest

from dbs.client.config import ServerProfile
from dbs.client.remote import (
    BackupOptions,
    build_backup_command,
    trigger_remote_backup,
)
from dbs.exceptions import ConfigurationError, DBSError
from dbs.transports.ssh import open_session

PASS = "correct horse battery staple"
REMOTE_DIR = "/var/backups/app"
REMOTE_PATH = f"{REMOTE_DIR}/backup-20260728-020000Z.dbs"


def profile(**overrides):
    values = {
        "name": "prod",
        "host": "app.example.com",
        "username": "deploy",
        "remote_dir": REMOTE_DIR,
        "project_dir": "/srv/myproject",
        "python": "/srv/myproject/.venv/bin/python",
    }
    values.update(overrides)
    return ServerProfile(**values)


def test_the_stdin_command_never_contains_the_passphrase():
    command = build_backup_command(profile(), REMOTE_PATH, BackupOptions())
    assert PASS not in command
    assert "--passphrase-stdin" in command
    assert "--passphrase " not in command


def test_the_env_command_never_contains_the_passphrase():
    command = build_backup_command(
        profile(passphrase_transport="env"), REMOTE_PATH, BackupOptions()
    )
    assert PASS not in command
    assert "IFS= read -r DBS_PASSPHRASE" in command
    assert "export DBS_PASSPHRASE" in command
    assert "--passphrase-stdin" not in command


def test_the_command_moves_to_the_project_and_names_the_settings():
    command = build_backup_command(
        profile(django_settings_module="myproject.settings.production"),
        REMOTE_PATH,
        BackupOptions(),
    )
    assert "cd /srv/myproject" in command
    assert "DJANGO_SETTINGS_MODULE=myproject.settings.production" in command
    assert "manage.py" in command


def test_a_project_without_extra_context_produces_a_bare_command():
    command = build_backup_command(
        ServerProfile(name="p", host="h", username="u"), REMOTE_PATH, BackupOptions()
    )
    assert "cd " not in command
    assert "DJANGO_SETTINGS_MODULE" not in command


def test_awkward_paths_are_quoted():
    command = build_backup_command(
        profile(project_dir="/srv/my project's app"),
        "/var/backups/we ird.dbs",
        BackupOptions(),
    )
    assert "my project" in command
    assert command.startswith("/bin/sh -c ")


def test_extra_environment_is_exported():
    command = build_backup_command(
        profile(env={"LC_ALL": "C.UTF-8"}), REMOTE_PATH, BackupOptions()
    )
    assert "export LC_ALL=C.UTF-8" in command


def test_every_backup_option_reaches_the_command():
    command = build_backup_command(
        profile(),
        REMOTE_PATH,
        BackupOptions(
            database="replica",
            compress=False,
            verify=False,
            block_size=4096,
            kdf_time=2,
            kdf_memory=16384,
        ),
    )
    for fragment in (
        "--database replica",
        "--no-compress",
        "--no-verify",
        "--block-size 4096",
        "--kdf-time 2",
        "--kdf-memory 16384",
    ):
        assert fragment in command


def test_defaults_do_not_emit_negative_flags():
    command = build_backup_command(profile(), REMOTE_PATH, BackupOptions())
    assert "--no-compress" not in command
    assert "--no-verify" not in command


def test_the_passphrase_arrives_on_stdin_and_the_stream_is_closed(fake_ssh):
    fake_ssh.make_remote_dir(REMOTE_DIR)
    with open_session(profile().ssh_target()) as session:
        trigger_remote_backup(session, profile(), PASS, "backup-20260728-020000Z.dbs")

    execution = fake_ssh.executions[0]
    assert execution.stdin == PASS + "\n"
    assert execution.stdin_closed is True
    assert PASS not in fake_ssh.commands[0]["command"]


def test_a_passphrase_with_a_line_break_is_refused_before_connecting(fake_ssh):
    fake_ssh.make_remote_dir(REMOTE_DIR)
    with open_session(profile().ssh_target()) as session:
        with pytest.raises(ConfigurationError):
            trigger_remote_backup(session, profile(), "two\nlines", "x.dbs")
    assert fake_ssh.commands == []


def test_a_failing_remote_backup_surfaces_its_stderr(fake_ssh):
    fake_ssh.make_remote_dir(REMOTE_DIR)
    fake_ssh.on_exec(lambda command, session: (1, "", "CommandError: bad passphrase"))

    with open_session(profile().ssh_target()) as session:
        with pytest.raises(DBSError) as excinfo:
            trigger_remote_backup(session, profile(), PASS, "x.dbs")

    assert "bad passphrase" in str(excinfo.value)
    assert "exit 1" in str(excinfo.value)


def test_the_remote_directory_is_created_before_the_backup_runs(fake_ssh):
    import os

    with open_session(profile().ssh_target()) as session:
        trigger_remote_backup(session, profile(), PASS, "x.dbs")

    assert os.path.isdir(fake_ssh.remote_path(REMOTE_DIR))


def test_the_exec_timeout_is_passed_through(fake_ssh):
    fake_ssh.make_remote_dir(REMOTE_DIR)
    with open_session(profile().ssh_target()) as session:
        trigger_remote_backup(session, profile(exec_timeout=120), PASS, "x.dbs")
    assert fake_ssh.commands[0]["timeout"] == 120
