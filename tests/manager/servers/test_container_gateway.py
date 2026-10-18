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
from dbs.manager.servers.gateways import ContainerTarget, DbsProfile, RemoteHost
from dbs.manager.servers.gateways.ssh_gateway import RECEIVE_FILE
from dbs.naming import backup_filename, is_backup_name
from tests.manager.servers.compose import CONTAINER_BACKUP_DIR, ComposeHost
from tests.manager.servers.support import BACKUP_PASSPHRASE, dbs_backup

PROJECT = "/srv/shop"
SERVICE = ContainerTarget(
    service="backend", files=("compose.yaml", "compose.prod.yaml"), project="shop"
)
PROFILE = DbsProfile(
    python="python",
    manage="manage.py",
    project_dir=PROJECT,
    settings_module="config.settings.prod",
    container=SERVICE,
)
COMPOSE_PREFIX = [
    "docker",
    "compose",
    "-f",
    "compose.yaml",
    "-f",
    "compose.prod.yaml",
    "-p",
    "shop",
]
TOKEN = "dbs.manager.servers.gateways.ssh_gateway.secrets.token_hex"

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


def streamed(host, folder=CONTAINER_BACKUP_DIR, profile=PROFILE):
    sink = io.BytesIO()
    found = RemoteHost(host).stream_dbs_backup(
        profile,
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


def test_a_service_with_a_workdir_runs_its_commands_there(folders):
    host = ComposeHost(folders["container"])
    profile = DbsProfile(
        python="/opt/venv/bin/python",
        manage="/app/manage.py",
        project_dir=PROJECT,
        container=ContainerTarget(service="backend", workdir="/app"),
    )

    RemoteHost(host).run_manage(profile, ["dbs", "health", "--json"])

    [run] = host.runs
    assert run["argv"] == [
        "docker",
        "compose",
        "exec",
        "-T",
        "-w",
        "/app",
        "backend",
        "/opt/venv/bin/python",
        "/app/manage.py",
        "dbs",
        "health",
        "--json",
    ]


def test_a_podman_service_runs_through_podman_compose(folders):
    host = ComposeHost(folders["container"], engine="podman")
    profile = DbsProfile(
        python="python",
        manage="manage.py",
        project_dir=PROJECT,
        container=ContainerTarget(engine="podman", service="backend"),
    )

    found, received = streamed(host, profile=profile)

    assert is_backup_name(found.name, "shop")
    assert validate_backup(received, BACKUP_PASSPHRASE).ok
    [run] = host.runs
    assert run["argv"][:5] == ["podman", "compose", "exec", "-T", "backend"]


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

    assert (
        RemoteHost(host).backup_folder(PROFILE, "/var/backups/dbs")
        == CONTAINER_BACKUP_DIR
    )
    assert RemoteHost(unset).backup_folder(PROFILE, "/var/backups/dbs") == ""
    assert host.runs[0]["argv"][-3:] == ["manage.py", "dbs_connection", "--json"]


def test_the_rest_of_a_backup_in_a_container_is_read_from_an_offset(folders):
    host = ComposeHost(folders["container"])
    folder = host.inside(CONTAINER_BACKUP_DIR)
    folder.mkdir(parents=True)
    name = backup_filename("shop")
    (folder / name).write_bytes(b"kept by the server")
    remote = RemoteHost(host)
    sink = io.BytesIO()

    remote.pull_backup(PROFILE, f"{CONTAINER_BACKUP_DIR}/{name}", sink, offset=8)

    assert sink.getvalue() == b"the server"
    assert host.runs[-1]["argv"][-4:] == [
        "-c",
        "+9",
        "--",
        f"{CONTAINER_BACKUP_DIR}/{name}",
    ]


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
    assert [
        *COMPOSE_PREFIX,
        "exec",
        "-T",
        "backend",
        "cat",
        "--",
        waiting.path,
    ] in argvs
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


def test_a_restore_streams_the_file_into_the_service_as_its_own_user(folders):
    host = ComposeHost(folders["container"])
    sent = dbs_backup(BACKUP_PASSPHRASE)

    report = restore(host, folders)

    assert (report.records, report.files) == (3, 0)
    assert report.copy_left == ""
    [fed] = [run for run in host.runs if run.get("fed")]
    inside = fed["argv"][-2]
    assert inside.startswith("/tmp/.dbs-restore-") and inside.endswith(".dbs")
    assert fed["argv"] == [
        *COMPOSE_PREFIX,
        "exec",
        "-T",
        "backend",
        "python",
        "-c",
        RECEIVE_FILE,
        inside,
        str(len(sent)),
    ]
    assert host.received[inside] == sent
    restore_run = next(run for run in host.runs if "dbs_restore" in run["argv"])
    assert restore_run["argv"][-4:] == [
        "dbs_restore",
        inside,
        "--passphrase-stdin",
        "--dry-run",
    ]
    assert restore_run["stdin"] == BACKUP_PASSPHRASE
    assert [*COMPOSE_PREFIX, "exec", "-T", "backend", "rm", "-f", "--", inside] in [
        run["argv"] for run in host.runs
    ]
    assert list(folders["container"].rglob("*.dbs")) == []
    assert not folders["host"].exists()
    assert host.sftp.opened == []


def test_a_restore_needs_no_root_no_copy_and_no_change_of_owner(folders):
    host = ComposeHost(folders["container"])

    restore(host, folders)

    for run in host.runs:
        assert "-u" not in run["argv"]
        assert "cp" not in run["argv"]
        assert "chown" not in run["argv"]


def test_a_real_restore_with_flush_passes_both_flags(folders):
    host = ComposeHost(folders["container"])

    report = restore(host, folders, dry_run=False, flush=True)

    assert report.records == 3
    restore_run = next(run for run in host.runs if "dbs_restore" in run["argv"])
    assert restore_run["argv"][-2:] == ["--passphrase-stdin", "--flush"]


def test_a_restore_into_a_stopped_service_stops_before_it_starts(folders):
    host = ComposeHost(folders["container"], running=("db",))

    with pytest.raises(RestoreFailed) as failed:
        restore(host, folders)

    assert 'service "backend" is not running' in failed.value.output
    assert not any("dbs_restore" in run["argv"] for run in host.runs)
    assert not folders["host"].exists()


def test_a_file_the_container_already_has_is_never_written_over(folders, monkeypatch):
    host = ComposeHost(folders["container"])
    monkeypatch.setattr(TOKEN, lambda size: "0" * (2 * size))
    taken = host.inside("/tmp/.dbs-restore-0000000000000000.dbs")
    taken.parent.mkdir(parents=True)
    taken.write_bytes(b"someone else's")

    with pytest.raises(RestoreFailed):
        restore(host, folders)

    assert taken.read_bytes() == b"someone else's"
    assert not any("dbs_restore" in run["argv"] for run in host.runs)


def test_a_restore_that_fails_in_the_container_still_removes_its_copy(folders):
    host = ComposeHost(folders["container"], with_dbs=())

    with pytest.raises(RestoreFailed):
        restore(host, folders)

    assert any(run["argv"][-4:-1] == ["rm", "-f", "--"] for run in host.runs)
    assert list(folders["container"].rglob("*.dbs")) == []


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        (
            ContainerTarget(service="web"),
            ["docker", "compose", "exec", "-T", "web", "id"],
        ),
        (
            ContainerTarget(service="web", files=("a.yaml",)),
            ["docker", "compose", "-f", "a.yaml", "exec", "-T", "web", "id"],
        ),
        (
            ContainerTarget(service="web", files=("a.yaml",), project="shop"),
            [
                "docker",
                "compose",
                "-f",
                "a.yaml",
                "-p",
                "shop",
                "exec",
                "-T",
                "web",
                "id",
            ],
        ),
    ],
)
def test_compose_files_and_project_come_before_the_command(target, expected):
    assert target.exec_argv(["id"]) == expected
