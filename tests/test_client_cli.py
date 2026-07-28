"""The dbs-client command, end to end against a fake server that writes real backups."""

import json
import os

import pytest

from dbs.client.cli import main
from dbs.engine import create_backup
from dbs.naming import backup_filename
from tests.conftest import FAST_KDF
from tests.testapp.models import Author

PASS = "client-pass-phrase"
REMOTE_DIR = "/var/backups/app"

CONFIG = """
[defaults]
server = "prod"

[servers.prod]
host = "app.example.com"
username = "deploy"
remote_dir = "{remote_dir}"
project_dir = "/srv/myproject"
python = "/srv/myproject/.venv/bin/python"
passphrase_env = "DBS_PASSPHRASE"
dest = "{dest}"
"""


@pytest.fixture
def container(db):
    Author.objects.create(name="Ada")
    return create_backup(PASS, kdf_params=FAST_KDF)


@pytest.fixture
def client_env(tmp_path, monkeypatch, fake_ssh, container):
    dest = tmp_path / "downloads"
    dest.mkdir()
    config = tmp_path / "dbs-client.toml"
    config.write_text(CONFIG.format(remote_dir=REMOTE_DIR, dest=str(dest)))
    os.chmod(config, 0o600)
    monkeypatch.setenv("DBS_PASSPHRASE", PASS)

    def serve(command, session):
        remote_path = _target_path(command)
        if remote_path is None:
            return 0, "0.2.0\n", ""
        os.makedirs(os.path.dirname(fake_ssh.remote_path(remote_path)), exist_ok=True)
        with open(fake_ssh.remote_path(remote_path), "wb") as fh:
            fh.write(container)
        return 0, "Wrote backup\n", ""

    fake_ssh.on_exec(serve)
    return {"config": str(config), "dest": dest, "fake": fake_ssh}


def _target_path(command):
    for token in command.split():
        if token.endswith(".dbs'") or token.endswith(".dbs"):
            return token.strip("'")
    return None


def run(client_env, *argv):
    return main(["--config", client_env["config"], *argv])


def test_backup_triggers_downloads_and_validates(client_env, capsys):
    assert run(client_env, "backup") == 0

    downloaded = list(client_env["dest"].iterdir())
    assert len(downloaded) == 1
    assert downloaded[0].name.endswith(".dbs")
    assert "Downloaded" in capsys.readouterr().out
    assert not any(path.name.endswith(".part") for path in client_env["dest"].iterdir())


def test_backup_can_leave_the_file_on_the_server(client_env, capsys):
    assert run(client_env, "backup", "--no-fetch") == 0

    assert list(client_env["dest"].iterdir()) == []
    assert "Created" in capsys.readouterr().out


def test_backup_can_delete_the_remote_copy(client_env):
    assert run(client_env, "backup", "--delete-remote") == 0

    assert len(list(client_env["dest"].iterdir())) == 1
    assert os.listdir(client_env["fake"].remote_path(REMOTE_DIR)) == []


def test_backup_applies_retention_on_both_sides(client_env):
    for hour in range(3):
        stale = backup_filename(moment=_moment(hour))
        (client_env["dest"] / stale).write_bytes(b"old")
        client_env["fake"].write_remote(REMOTE_DIR, stale, b"old")

    assert run(client_env, "backup", "--keep", "2", "--keep-remote", "2") == 0

    assert len(list(client_env["dest"].iterdir())) == 2
    assert len(os.listdir(client_env["fake"].remote_path(REMOTE_DIR))) == 2


def test_list_reports_what_is_on_the_server(client_env, capsys):
    name = backup_filename(moment=_moment(0))
    client_env["fake"].write_remote(REMOTE_DIR, name, b"payload")
    client_env["fake"].write_remote(REMOTE_DIR, "notes.txt", b"hello")

    assert run(client_env, "list") == 0
    out = capsys.readouterr().out
    assert name in out
    assert "notes.txt" not in out

    assert run(client_env, "list", "--all") == 0
    assert "notes.txt" in capsys.readouterr().out


def test_list_json_is_machine_readable(client_env, capsys):
    name = backup_filename(moment=_moment(0))
    client_env["fake"].write_remote(REMOTE_DIR, name, b"payload")

    assert run(client_env, "list", "--json") == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed[0]["name"] == name
    assert parsed[0]["size"] == 7


def test_list_says_so_when_the_server_has_nothing(client_env, capsys):
    client_env["fake"].make_remote_dir(REMOTE_DIR)
    assert run(client_env, "list") == 0
    assert "No backups" in capsys.readouterr().out


def test_pull_latest_takes_the_newest(client_env, container, capsys):
    older = backup_filename(moment=_moment(0))
    newer = backup_filename(moment=_moment(5))
    client_env["fake"].write_remote(REMOTE_DIR, older, container)
    client_env["fake"].write_remote(REMOTE_DIR, newer, container)

    assert run(client_env, "pull", "--latest") == 0

    assert [path.name for path in client_env["dest"].iterdir()] == [newer]
    assert newer in capsys.readouterr().out


def test_pull_needs_a_name_or_latest(client_env, capsys):
    assert run(client_env, "pull") == 1
    assert "--latest" in capsys.readouterr().err


def test_pull_reports_an_empty_server(client_env, capsys):
    client_env["fake"].make_remote_dir(REMOTE_DIR)
    assert run(client_env, "pull", "--latest") == 1
    assert "no backups" in capsys.readouterr().err


def test_push_uploads_a_local_file(client_env, tmp_path, container, capsys):
    local = tmp_path / backup_filename(moment=_moment(0))
    local.write_bytes(container)

    assert run(client_env, "push", str(local)) == 0

    assert local.name in os.listdir(client_env["fake"].remote_path(REMOTE_DIR))
    assert "Uploaded" in capsys.readouterr().out


def test_prune_dry_run_removes_nothing(client_env, capsys):
    for hour in range(4):
        stale = backup_filename(moment=_moment(hour))
        (client_env["dest"] / stale).write_bytes(b"old")
        client_env["fake"].write_remote(REMOTE_DIR, stale, b"old")

    assert run(client_env, "prune", "--keep", "1", "--keep-remote", "1", "--dry-run") == 0

    assert "Would remove" in capsys.readouterr().out
    assert len(list(client_env["dest"].iterdir())) == 4
    assert len(os.listdir(client_env["fake"].remote_path(REMOTE_DIR))) == 4


def test_prune_local_only_leaves_the_server_alone(client_env):
    for hour in range(3):
        stale = backup_filename(moment=_moment(hour))
        (client_env["dest"] / stale).write_bytes(b"old")
        client_env["fake"].write_remote(REMOTE_DIR, stale, b"old")

    assert run(client_env, "prune", "--keep", "1", "--local-only") == 0

    assert len(list(client_env["dest"].iterdir())) == 1
    assert len(os.listdir(client_env["fake"].remote_path(REMOTE_DIR))) == 3


def test_prune_needs_a_retention_count(client_env, capsys):
    assert run(client_env, "prune", "--local-only") == 1
    assert "--keep" in capsys.readouterr().err


def test_test_connection_reports_each_check(client_env, capsys):
    assert run(client_env, "test-connection") == 0
    out = capsys.readouterr().out
    assert "ssh authentication" in out
    assert "reject-unknown" in out
    assert "django-dbs on server" in out
    assert "FAIL" not in out


def test_test_connection_fails_when_the_server_cannot_run_the_command(
    client_env, capsys
):
    client_env["fake"].on_exec(lambda command, session: (127, "", "not found"))

    assert run(client_env, "test-connection") == 1
    assert "FAIL" in capsys.readouterr().out


def test_schedule_once_runs_a_single_cycle(client_env):
    assert run(client_env, "schedule", "--once") == 0
    assert len(list(client_env["dest"].iterdir())) == 1


def test_schedule_reports_a_failing_cycle(client_env):
    client_env["fake"].on_exec(lambda command, session: (1, "", "boom"))
    assert run(client_env, "schedule", "--once") == 1


def test_validate_checks_a_local_file(tmp_path, container, capsys, monkeypatch):
    monkeypatch.delenv("DBS_PASSPHRASE", raising=False)
    path = tmp_path / "local.dbs"
    path.write_bytes(container)

    assert main(["validate", str(path), "--structure-only"]) == 0
    assert "VALID" in capsys.readouterr().out


def test_validate_rejects_a_damaged_file(tmp_path, container, capsys):
    path = tmp_path / "broken.dbs"
    path.write_bytes(b"not a container at all")

    assert main(["validate", str(path), "--structure-only"]) == 1
    assert "INVALID" in capsys.readouterr().out


def test_init_writes_a_private_config(tmp_path, capsys):
    path = tmp_path / "written.toml"

    assert main(["init", "--path", str(path)]) == 0

    assert oct(os.stat(path).st_mode)[-3:] == "600"
    assert "servers.production" in path.read_text()
    assert "Wrote" in capsys.readouterr().out


def test_init_never_overwrites(tmp_path, capsys):
    path = tmp_path / "written.toml"
    path.write_text("mine")

    assert main(["init", "--path", str(path)]) == 1

    assert path.read_text() == "mine"
    assert "already exists" in capsys.readouterr().err


def test_init_print_produces_a_loadable_config(tmp_path, capsys, monkeypatch):
    assert main(["init", "--print"]) == 0
    text = capsys.readouterr().out

    path = tmp_path / "dbs-client.toml"
    path.write_text(text)
    os.chmod(path, 0o600)

    from dbs.client.config import load_client_config

    config = load_client_config(str(path))
    assert config.server().name == "production"
    assert config.server("staging").password_env == "DBS_STAGING_SSH_PASSWORD"


def test_an_unknown_subcommand_is_a_usage_error():
    with pytest.raises(SystemExit) as excinfo:
        main(["nonsense"])
    assert excinfo.value.code == 2


def test_a_configuration_problem_is_reported_without_a_traceback(tmp_path, capsys):
    assert main(["--config", str(tmp_path / "absent.toml"), "list"]) == 1
    assert capsys.readouterr().err.startswith("error: ")


def _moment(hour):
    import datetime

    return datetime.datetime(2026, 1, 1, hour, 0, 0, tzinfo=datetime.timezone.utc)
