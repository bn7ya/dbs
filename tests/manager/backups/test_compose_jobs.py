from __future__ import annotations

import pytest

from dbs import audit, validate_backup
from dbs.manager.applications.models import Application
from dbs.manager.backups.repositories import BackupFileRepository
from dbs.manager.redeploy.services import RedeployService
from dbs.manager.servers.gateways.ssh_gateway import RECEIVE_FILE
from tests.manager.factories import make_application
from tests.manager.servers.compose import (
    CONTAINER_BACKUP_DIR,
    ComposeHost,
    connected_to,
)
from tests.manager.servers.support import BACKUP_PASSPHRASE

TAKE = "/api/backups/take/"


@pytest.fixture
def host_backups(tmp_path):
    backups = tmp_path / "host" / "backups"
    backups.mkdir(parents=True)
    return backups


@pytest.fixture
def compose_application(admin, host_backups) -> Application:
    return make_application(
        admin,
        name="shop",
        host="10.0.0.7",
        kind=Application.Kind.COMPOSE,
        engine=Application.Engine.DOCKER,
        compose_service="backend",
        compose_files=["compose.yaml"],
        project_dir="/srv/shop",
        python_path="python",
        remote_backup_dir=str(host_backups),
        backup_passphrase=BACKUP_PASSPHRASE,
    )


@pytest.fixture
def docker_host(monkeypatch, tmp_path) -> ComposeHost:
    return connected_to(monkeypatch, ComposeHost(tmp_path / "container"))


def service_of(run: dict) -> str:
    return run["argv"][run["argv"].index("exec") + 2]


@pytest.mark.django_db
def test_a_take_from_a_compose_application_stores_a_backup_that_decrypts(
    api, compose_application, docker_host, run_jobs, entry, storage
):
    with run_jobs():
        response = api.post(TAKE, {"application": compose_application.pk})

    job = entry(response.json()["activity"])
    assert job.status == audit.SUCCEEDED
    [file] = BackupFileRepository().alive_for_application(compose_application.pk)
    assert not file.sealed
    content = (storage / file.storage_path).read_bytes()
    result = validate_backup(content, BACKUP_PASSPHRASE)
    assert result.ok and result.decrypted_ok
    assert file.validation == "verified"
    assert file.remote_path == ""
    assert list(docker_host.inside(CONTAINER_BACKUP_DIR).iterdir()) == []
    [streamed] = [run for run in docker_host.runs if "dbs_backup" in run["argv"]]
    assert streamed["argv"][-7:] == [
        "dbs_backup",
        "--stream",
        "--prefix",
        "shop",
        "--passphrase-stdin",
        "--output-dir",
        CONTAINER_BACKUP_DIR,
    ]
    assert streamed["stdin"] == BACKUP_PASSPHRASE


@pytest.mark.django_db
def test_a_rehearsed_restore_into_a_compose_application_streams_the_file_in(
    api, compose_application, docker_host, host_backups, run_jobs, entry, storage
):
    with run_jobs():
        taken = api.post(TAKE, {"application": compose_application.pk})
    assert entry(taken.json()["activity"]).status == audit.SUCCEEDED
    [backup] = BackupFileRepository().alive_for_application(compose_application.pk)

    with run_jobs():
        response = api.post(
            f"/api/backups/{backup.pk}/restore/",
            {"mode": "merge", "rehearse": True},
            format="json",
        )

    job = entry(response.json()["activity"])
    assert job.status == audit.SUCCEEDED
    assert (job.data["records"], job.data["files"]) == (3, 0)
    [fed] = [run for run in docker_host.runs if run.get("fed")]
    path = fed["argv"][fed["argv"].index(RECEIVE_FILE) + 1]
    assert path.startswith("/tmp/.dbs-restore-") and path.endswith(".dbs")
    assert service_of(fed) == "backend"
    assert "-u" not in fed["argv"]
    assert docker_host.received[path] == (storage / backup.storage_path).read_bytes()
    [restored] = [run for run in docker_host.runs if "dbs_restore" in run["argv"]]
    assert service_of(restored) == "backend"
    assert restored["argv"][restored["argv"].index("dbs_restore") + 1] == path
    assert restored["stdin"] == BACKUP_PASSPHRASE
    [removed] = [
        run for run in docker_host.runs if run["argv"][-4:] == ["rm", "-f", "--", path]
    ]
    assert service_of(removed) == "backend"
    assert "-u" not in removed["argv"]
    assert not docker_host.inside(path).exists()
    assert "copy_left" not in job.data
    assert list(host_backups.iterdir()) == []
    for run in docker_host.runs:
        assert "cp" not in run["argv"]
        assert "chown" not in run["argv"]


@pytest.mark.django_db
def test_a_restore_the_service_cannot_receive_fails_with_its_output(
    api, compose_application, docker_host, run_jobs, entry
):
    with run_jobs():
        api.post(TAKE, {"application": compose_application.pk})
    [backup] = BackupFileRepository().alive_for_application(compose_application.pk)
    docker_host.running = ("db",)

    with run_jobs():
        response = api.post(
            f"/api/backups/{backup.pk}/restore/",
            {"mode": "merge", "rehearse": True},
            format="json",
        )

    job = entry(response.json()["activity"])
    assert (job.status, job.error_code) == (audit.FAILED, "restore_failed")
    assert job.data["output"] == 'service "backend" is not running'
    assert docker_host.received == {}
    assert not any("dbs_restore" in run["argv"] for run in docker_host.runs)


@pytest.mark.django_db
def test_redeploy_migrates_inside_the_service(admin, compose_application, docker_host):
    result = RedeployService(admin)._manage(
        compose_application, admin, "migrate", "--noinput"
    )

    assert result.ok
    [run] = docker_host.runs
    assert run["argv"] == [
        "docker",
        "compose",
        "-f",
        "compose.yaml",
        "exec",
        "-T",
        "backend",
        "python",
        "manage.py",
        "migrate",
        "--noinput",
    ]
