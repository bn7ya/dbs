from __future__ import annotations

import io
import stat

import pytest

from dbs import validate_backup
from dbs.manager.servers.exceptions import RemoteCommandFailed, RestoreFailed
from dbs.manager.servers.gateways import ComposeService, DbsProfile, RemoteHost
from dbs.naming import is_backup_name
from tests.manager.servers.compose import ComposeHost
from tests.manager.servers.support import BACKUP_PASSPHRASE, dbs_backup

PROJECT = "/srv/shop"
COMPOSE = ComposeService(service="backend", files=("compose.yaml", "compose.prod.yaml"))
PROFILE = DbsProfile(
    python="python",
    manage="manage.py",
    project_dir=PROJECT,
    settings_module="config.settings.prod",
    compose=COMPOSE,
)
COMPOSE_PREFIX = ["docker", "compose", "-f", "compose.yaml", "-f", "compose.prod.yaml"]

pytestmark = pytest.mark.django_db


@pytest.fixture
def folders(tmp_path):
    host_dir = tmp_path / "host" / "backups"
    manager_dir = tmp_path / "manager"
    manager_dir.mkdir()
    return {
        "host": host_dir,
        "manager": manager_dir,
        "container": tmp_path / "container",
    }


def take(host, folders, keep_remote=2):
    return RemoteHost(host).take_dbs_backup(
        profile=PROFILE,
        passphrase=BACKUP_PASSPHRASE,
        dest_dir=str(folders["manager"]),
        prefix="shop",
        keep_remote=keep_remote,
        remote_dir=str(folders["host"]),
    )


def restore(host, folders, *, dry_run=True, flush=False):
    return RemoteHost(host).restore_dbs_backup(
        io.BytesIO(dbs_backup(BACKUP_PASSPHRASE)),
        profile=PROFILE,
        passphrase=BACKUP_PASSPHRASE,
        remote_dir=str(folders["host"]),
        flush=flush,
        dry_run=dry_run,
    )


def test_a_manage_command_runs_inside_the_service_from_the_project_folder(folders):
    host = ComposeHost(folders["container"])

    result = RemoteHost(host).run_manage(PROFILE, ["dbs", "health", "--json"])

    assert result.ok
    [run] = host.runs
    assert run["argv"] == [
        *COMPOSE_PREFIX,
        "exec",
        "-T",
        "-e",
        "DJANGO_SETTINGS_MODULE=config.settings.prod",
        "backend",
        "python",
        "manage.py",
        "dbs",
        "health",
        "--json",
    ]
    assert run["setup"] == [f"cd {PROJECT} || exit 1"]


def test_a_backup_is_made_in_the_container_copied_out_and_fetched(folders):
    host = ComposeHost(folders["container"])

    fetched = take(host, folders)

    local = folders["manager"] / fetched.local_path.rsplit("/", 1)[1]
    assert is_backup_name(local.name, "shop")
    result = validate_backup(local.read_bytes(), BACKUP_PASSPHRASE)
    assert result.ok and result.decrypted_ok
    assert stat.S_IMODE(local.stat().st_mode) == 0o600
    assert fetched.remote_path == str(folders["host"] / local.name)
    assert (folders["host"] / local.name).read_bytes() == local.read_bytes()
    assert list(folders["container"].rglob("*.dbs")) == []
    backup_run = next(run for run in host.runs if "dbs_backup" in run["argv"])
    assert backup_run["stdin"] == BACKUP_PASSPHRASE
    assert BACKUP_PASSPHRASE not in " ".join(
        part for run in host.runs for part in run["argv"]
    )
    inside = backup_run["argv"][backup_run["argv"].index("dbs_backup") + 1]
    assert inside.startswith("/tmp/.dbs-backup-")
    assert [*COMPOSE_PREFIX, "cp", f"backend:{inside}", fetched.remote_path] in [
        run["argv"] for run in host.runs
    ]


def test_keeping_no_copy_on_the_server_removes_it_once_fetched(folders):
    host = ComposeHost(folders["container"])

    fetched = take(host, folders, keep_remote=0)

    assert fetched.remote_path == ""
    assert list(folders["host"].iterdir()) == []


def test_the_server_keeps_only_the_newest_copies(folders):
    host = ComposeHost(folders["container"])
    folders["host"].mkdir(parents=True)
    (folders["host"] / "shop-20260101-000000Z.dbs").write_bytes(b"old")
    (folders["host"] / "notes.txt").write_text("not a backup")

    take(host, folders, keep_remote=1)

    kept = sorted(path.name for path in folders["host"].iterdir())
    assert len(kept) == 2 and "notes.txt" in kept
    assert "shop-20260101-000000Z.dbs" not in kept


def test_a_backup_that_fails_in_the_container_says_why_and_leaves_nothing(folders):
    printed = f"read {BACKUP_PASSPHRASE} from stdin\nCommandError: the database is not reachable"
    host = ComposeHost(folders["container"], backup_fails=printed)

    with pytest.raises(RemoteCommandFailed) as failed:
        take(host, folders)

    assert failed.value.output.endswith("CommandError: the database is not reachable")
    assert BACKUP_PASSPHRASE not in failed.value.output
    assert list(folders["manager"].iterdir()) == []
    assert any(run["argv"][-3:-1] == ["rm", "-f"] for run in host.runs)


def test_a_service_that_is_not_running_is_reported(folders):
    host = ComposeHost(folders["container"], running=("db",))

    with pytest.raises(RemoteCommandFailed) as failed:
        take(host, folders)

    assert 'service "backend" is not running' in failed.value.output
    assert list(folders["manager"].iterdir()) == []


def test_a_restore_hands_the_file_to_the_container_user_and_cleans_up(folders):
    host = ComposeHost(folders["container"])

    report = restore(host, folders)

    assert (report.records, report.files) == (3, 0)
    assert report.copy_left == ""
    argvs = [run["argv"] for run in host.runs]
    [copied] = [argv for argv in argvs if "cp" in argv]
    inside = copied[-1].split(":", 1)[1]
    assert inside.startswith("/tmp/.dbs-restore-")
    assert [
        *COMPOSE_PREFIX,
        "exec",
        "-T",
        "-u",
        "0",
        "backend",
        "chown",
        "10001",
        inside,
    ] in argvs
    restore_run = next(run for run in host.runs if "dbs_restore" in run["argv"])
    assert restore_run["argv"][-4:] == [
        "dbs_restore",
        inside,
        "--passphrase-stdin",
        "--dry-run",
    ]
    assert restore_run["stdin"] == BACKUP_PASSPHRASE
    assert list(folders["container"].rglob("*.dbs")) == []
    assert list(folders["host"].iterdir()) == []


def test_a_real_restore_with_flush_passes_both_flags(folders):
    host = ComposeHost(folders["container"])

    report = restore(host, folders, dry_run=False, flush=True)

    assert report.records == 3
    restore_run = next(run for run in host.runs if "dbs_restore" in run["argv"])
    assert restore_run["argv"][-2:] == ["--passphrase-stdin", "--flush"]


def test_a_container_running_as_root_is_handed_the_file_as_root(folders):
    host = ComposeHost(folders["container"], container_uid="0")

    report = restore(host, folders)

    assert report.records == 3


def test_a_file_the_container_user_cannot_be_given_stops_the_restore(folders):
    host = ComposeHost(folders["container"], chown_fails=True)

    with pytest.raises(RestoreFailed) as failed:
        restore(host, folders)

    assert "Operation not permitted" in failed.value.output
    assert not any("dbs_restore" in run["argv"] for run in host.runs)
    assert list(folders["container"].rglob("*.dbs")) == []
    assert list(folders["host"].iterdir()) == []


def test_a_restore_into_a_stopped_service_stops_before_it_starts(folders):
    host = ComposeHost(folders["container"], running=("db",))

    with pytest.raises(RestoreFailed) as failed:
        restore(host, folders)

    assert 'service "backend" is not running' in failed.value.output
    assert list(folders["host"].iterdir()) == []


@pytest.mark.parametrize(
    ("compose", "expected"),
    [
        (ComposeService("web"), ["docker", "compose", "exec", "-T", "web", "id"]),
        (
            ComposeService("web", ("a.yaml",)),
            ["docker", "compose", "-f", "a.yaml", "exec", "-T", "web", "id"],
        ),
    ],
)
def test_compose_files_come_before_the_command(compose, expected):
    assert compose.exec_argv(["id"]) == expected
