"""The unattended server-side scheduler."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from dbs.engine import validate_backup
from dbs.keys import default_passphrase
from dbs.naming import backup_filename, is_backup_name
from tests.testapp.models import Author

PASS = "schedule-pass-phrase"

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
def test_without_an_environment_passphrase_it_derives_one(tmp_path, monkeypatch):
    monkeypatch.delenv("DBS_PASSPHRASE", raising=False)
    Author.objects.create(name="Grace")

    call_command("dbs_schedule", "--once", output_dir=str(tmp_path), **FAST)

    written = list(tmp_path.iterdir())
    assert len(written) == 1
    validate_backup(written[0].read_bytes(), default_passphrase()).ok


@pytest.mark.django_db
def test_no_passphrase_and_no_secret_key_refuses_to_start(
    tmp_path, monkeypatch, settings
):
    monkeypatch.delenv("DBS_PASSPHRASE", raising=False)
    settings.SECRET_KEY = ""
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
def test_an_output_directory_that_cannot_be_created_is_reported(tmp_path, passphrase_env):
    blocker = tmp_path / "a-file"
    blocker.write_text("not a folder")

    with pytest.raises(CommandError) as excinfo:
        call_command("dbs_schedule", "--once", output_dir=str(blocker / "backups"), **FAST)

    assert str(blocker / "backups") in str(excinfo.value)


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
    from tests.format1 import write_container

    for hour in range(4):
        stale = backup_filename(moment=_moment(hour))
        manifest = {
            "created": _moment(hour).isoformat(),
            "blocks": {"block_size": 1024},
            "copy_len": 0,
        }
        (tmp_path / stale).write_bytes(write_container(manifest, b"", b"", flags=0))
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


@pytest.mark.parametrize("flag", ["--push", "--keep-remote"])
def test_the_server_pushes_nowhere(flag, tmp_path, passphrase_env):
    with pytest.raises(CommandError) as excinfo:
        call_command("dbs_schedule", "--once", f"--output-dir={tmp_path}", flag, "1")

    assert "unrecognized arguments" in str(excinfo.value)
    assert not list(tmp_path.iterdir())


def _moment(hour):
    import datetime

    return datetime.datetime(2026, 1, 1, hour, 0, 0, tzinfo=datetime.timezone.utc)
