"""The unattended server-side scheduler."""

import os
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from dbs.naming import backup_filename, is_backup_name
from tests.testapp.models import Author

PASS = "schedule-pass-phrase"
REMOTE_DIR = "/var/backups/app"

FAST = {"kdf_time": 1, "kdf_memory": 8192}


@pytest.fixture
def passphrase_env(monkeypatch):
    monkeypatch.setenv("DBS_PASSPHRASE", PASS)


@pytest.mark.django_db
def test_once_writes_a_convention_named_backup(tmp_path, passphrase_env):
    Author.objects.create(name="Ada")
    out = StringIO()

    call_command("dbs_schedule", "--once", output_dir=str(tmp_path), stdout=out, **FAST)

    written = list(tmp_path.iterdir())
    assert len(written) == 1
    assert is_backup_name(written[0].name)
    assert "complete" in out.getvalue()


@pytest.mark.django_db
def test_missing_passphrase_refuses_to_start(tmp_path, monkeypatch):
    monkeypatch.delenv("DBS_PASSPHRASE", raising=False)
    with pytest.raises(CommandError) as excinfo:
        call_command("dbs_schedule", "--once", output_dir=str(tmp_path), **FAST)
    assert "DBS_PASSPHRASE" in str(excinfo.value)


@pytest.mark.django_db
def test_an_output_directory_is_required(passphrase_env, settings):
    settings.DBS_BACKUP_DIR = None
    with pytest.raises(CommandError) as excinfo:
        call_command("dbs_schedule", "--once", **FAST)
    assert "DBS_BACKUP_DIR" in str(excinfo.value)


@pytest.mark.django_db
def test_output_directory_is_created_and_read_from_settings(
    tmp_path, passphrase_env, settings
):
    destination = tmp_path / "nested" / "backups"
    settings.DBS_BACKUP_DIR = str(destination)

    call_command("dbs_schedule", "--once", **FAST)

    assert len(list(destination.iterdir())) == 1


@pytest.mark.django_db
def test_retention_keeps_only_the_newest(tmp_path, passphrase_env):
    for hour in range(4):
        stale = backup_filename(moment=_moment(hour))
        (tmp_path / stale).write_bytes(b"old")
    (tmp_path / "keep-me.sql").write_bytes(b"not a backup")

    call_command("dbs_schedule", "--once", output_dir=str(tmp_path), keep=2, **FAST)

    names = sorted(path.name for path in tmp_path.iterdir())
    assert "keep-me.sql" in names
    assert len([name for name in names if is_backup_name(name)]) == 2


@pytest.mark.django_db
def test_prefix_scopes_both_naming_and_retention(tmp_path, passphrase_env):
    other = backup_filename("staging", moment=_moment(0))
    (tmp_path / other).write_bytes(b"other project")

    call_command(
        "dbs_schedule", "--once", output_dir=str(tmp_path), prefix="prod", keep=1, **FAST
    )

    names = sorted(path.name for path in tmp_path.iterdir())
    assert other in names
    assert any(name.startswith("prod-") for name in names)


@pytest.mark.django_db
def test_push_sends_the_backup_and_prunes_the_remote(
    tmp_path, passphrase_env, settings, fake_ssh
):
    settings.DBS_SSH_TARGETS = {
        "offsite": {
            "host": "backups.example.com",
            "username": "deploy",
            "remote_dir": REMOTE_DIR,
        }
    }
    local_dir = tmp_path / "local"
    for hour in range(3):
        fake_ssh.write_remote(REMOTE_DIR, backup_filename(moment=_moment(hour)), b"old")

    call_command(
        "dbs_schedule",
        "--once",
        output_dir=str(local_dir),
        push="offsite",
        keep_remote=2,
        **FAST,
    )

    remote = sorted(os.listdir(fake_ssh.remote_path(REMOTE_DIR)))
    assert len(remote) == 2
    local = next(path for path in local_dir.iterdir())
    assert local.name in remote


def _moment(hour):
    import datetime

    return datetime.datetime(2026, 1, 1, hour, 0, 0, tzinfo=datetime.timezone.utc)
