from __future__ import annotations

import hashlib
import io

import pytest

from dbs import validate_backup
from dbs.manager.servers.exceptions import (
    RemoteCommandFailed,
    RestoreFailed,
    StreamBroken,
)
from dbs.manager.servers.gateways import ComposeService, DbsProfile, RemoteHost
from dbs.naming import backup_filename, is_backup_name
from tests.manager.servers.compose import CONTAINER_BACKUP_DIR, ComposeHost
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


def streamed(host, folder=CONTAINER_BACKUP_DIR):
    sink = io.BytesIO()
    found = RemoteHost(host).stream_dbs_backup(
        PROFILE,
        passphrase=BACKUP_PASSPHRASE,
        prefix="shop",
        folder=folder,
        sink=sink,
    )
    return found, sink.getvalue()


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


def test_a_backup_streams_out_of_the_service_and_the_container_keeps_a_copy(
    folders,
):
    host = ComposeHost(folders["container"])

    found, received = streamed(host)

    assert is_backup_name(found.name, "shop")
    assert found.path == f"{CONTAINER_BACKUP_DIR}/{found.name}"
    result = validate_backup(received, BACKUP_PASSPHRASE)
    assert result.ok and result.decrypted_ok
    assert found.sha256 == hashlib.sha256(received).hexdigest()
    assert host.inside(found.path).read_bytes() == received
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
        "dbs_backup",
        "--stream",
        "--prefix",
        "shop",
        "--passphrase-stdin",
        "--output-dir",
        CONTAINER_BACKUP_DIR,
    ]
    assert run["setup"] == [f"cd {PROJECT} || exit 1"]
    assert run["stdin"] == BACKUP_PASSPHRASE
    assert BACKUP_PASSPHRASE not in " ".join(run["argv"])


def test_the_service_names_where_it_keeps_its_backups(folders):
    host = ComposeHost(folders["container"])
    unset = ComposeHost(folders["container"], backup_dir="")

    assert RemoteHost(host).backup_folder(PROFILE, "/var/backups/dbs") == CONTAINER_BACKUP_DIR
    assert RemoteHost(unset).backup_folder(PROFILE, "/var/backups/dbs") == ""
    assert host.runs[0]["argv"][-3:] == ["manage.py", "dbs_connection", "--json"]


def test_backups_waiting_in_the_container_are_listed_pulled_checked_and_removed(
    folders,
):
    host = ComposeHost(folders["container"])
    folder = host.inside(CONTAINER_BACKUP_DIR)
    folder.mkdir(parents=True)
    name = backup_filename("shop")
    (folder / name).write_bytes(b"kept by the server")
    (folder / backup_filename("other")).write_bytes(b"not this prefix")
    (folder / "notes.txt").write_text("not a backup")
    remote = RemoteHost(host)

    [waiting] = remote.waiting_backups(PROFILE, CONTAINER_BACKUP_DIR, "shop")
    sink = io.BytesIO()
    remote.pull_backup(PROFILE, waiting.path, sink)
    digest = remote.backup_sha256(PROFILE, waiting.path)
    remote.remove_backup(PROFILE, waiting.path)

    assert (waiting.name, waiting.size) == (name, len(b"kept by the server"))
    assert sink.getvalue() == b"kept by the server"
    assert digest == hashlib.sha256(b"kept by the server").hexdigest()
    assert not (folder / name).exists()
    argvs = [run["argv"] for run in host.runs]
    assert [*COMPOSE_PREFIX, "exec", "-T", "backend", "cat", "--", waiting.path] in argvs
    assert [
        *COMPOSE_PREFIX,
        "exec",
        "-T",
        "backend",
        "rm",
        "-f",
        "--",
        waiting.path,
    ] in argvs


def test_nothing_waits_in_a_folder_the_container_does_not_have(folders):
    host = ComposeHost(folders["container"])

    assert RemoteHost(host).waiting_backups(PROFILE, CONTAINER_BACKUP_DIR, "shop") == []


def test_a_backup_that_fails_in_the_container_says_why(folders):
    printed = f"read {BACKUP_PASSPHRASE} from stdin\nCommandError: the database is not reachable"
    host = ComposeHost(folders["container"], backup_fails=printed)

    with pytest.raises(RemoteCommandFailed) as failed:
        streamed(host)

    assert failed.value.output.endswith("CommandError: the database is not reachable")
    assert BACKUP_PASSPHRASE not in failed.value.output


def test_a_service_that_is_not_running_is_reported(folders):
    host = ComposeHost(folders["container"], running=("db",))

    with pytest.raises(RemoteCommandFailed) as failed:
        streamed(host)

    assert 'service "backend" is not running' in failed.value.output


def test_a_connection_lost_while_the_service_streams_leaves_the_copy_inside(folders):
    host = ComposeHost(folders["container"], stream_breaks=True)

    with pytest.raises(StreamBroken):
        streamed(host)

    [kept] = list(host.inside(CONTAINER_BACKUP_DIR).iterdir())
    assert is_backup_name(kept.name, "shop")


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
