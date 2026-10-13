from __future__ import annotations

import pytest

from dbs import audit, validate_backup
from dbs.manager.backups.repositories import BackupFileRepository
from dbs.manager.redeploy.services import RedeployService
from dbs.manager.servers.models import Server
from dbs.manager.servers.services import ServerService
from tests.manager.servers.compose import (
    CONTAINER_BACKUP_DIR,
    ComposeHost,
    connected_to,
)
from tests.manager.servers.support import (
    BACKUP_PASSPHRASE,
    host_key_line,
    private_key_text,
)

TAKE = "/api/backups/take/"


@pytest.fixture
def compose_server(admin, tmp_path) -> Server:
    backups = tmp_path / "host" / "backups"
    backups.mkdir(parents=True)
    return ServerService(admin).create(
        name="shop",
        host="10.0.0.7",
        username="deploy",
        auth_method=Server.AuthMethod.KEY,
        private_key=private_key_text(),
        host_key=host_key_line(),
        runtime=Server.Runtime.COMPOSE,
        compose_service="backend",
        compose_files=["compose.yaml"],
        project_dir="/srv/shop",
        python_path="python",
        remote_backup_dir=str(backups),
        backup_passphrase=BACKUP_PASSPHRASE,
    )


@pytest.fixture
def docker_host(monkeypatch, tmp_path) -> ComposeHost:
    return connected_to(monkeypatch, ComposeHost(tmp_path / "container"))


@pytest.mark.django_db
def test_a_take_from_a_compose_server_stores_a_backup_that_decrypts(
    api, compose_server, docker_host, run_jobs, entry, storage
):
    with run_jobs():
        response = api.post(TAKE, {"server": compose_server.pk})

    job = entry(response.json()["activity"])
    assert job.status == audit.SUCCEEDED
    [file] = BackupFileRepository().alive_for_server(compose_server.pk)
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
def test_a_rehearsed_restore_onto_a_compose_server_runs_in_the_service(
    api, compose_server, docker_host, run_jobs, entry
):
    with run_jobs():
        taken = api.post(TAKE, {"server": compose_server.pk})
    assert entry(taken.json()["activity"]).status == audit.SUCCEEDED
    [backup] = BackupFileRepository().alive_for_server(compose_server.pk)

    with run_jobs():
        response = api.post(
            f"/api/backups/{backup.pk}/restore/",
            {"mode": "merge", "rehearse": True},
            format="json",
        )

    job = entry(response.json()["activity"])
    assert job.status == audit.SUCCEEDED
    assert (job.data["records"], job.data["files"]) == (3, 0)
    [restored] = [run for run in docker_host.runs if "dbs_restore" in run["argv"]]
    assert restored["argv"][restored["argv"].index("exec") + 2] == "backend"


@pytest.mark.django_db
def test_redeploy_migrates_inside_the_service(admin, compose_server, docker_host):
    result = RedeployService(admin)._manage(
        compose_server, admin, "migrate", "--noinput"
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
