from __future__ import annotations

import pytest

from dbs.manager.applications.models import Application
from dbs.manager.applications.repositories import ApplicationRepository
from dbs.manager.applications.services import ApplicationService
from dbs.manager.servers.services import ServerConnectionService
from dbs.manager.servers.services.pythons import VERSION_PROBE
from tests.manager.factories import make_application
from tests.manager.servers.compose import COMPOSE_VERSION, ComposeHost, connected_to
from tests.manager.servers.support import BACKUP_PASSPHRASE, REMOTE_DBS_VERSION

APPLICATIONS = "/api/applications/"
PROJECT = "/srv/shop"


def detail(application, action=""):
    return f"{APPLICATIONS}{application.pk}/{action}"


def compose_settings(server, **overrides):
    return {
        "server": str(server.pk),
        "name": "shop",
        "backup_passphrase": BACKUP_PASSPHRASE,
        "kind": "compose",
        "engine": "docker",
        "compose_service": "backend",
        "compose_files": ["compose.yaml", "compose.prod.yaml"],
        "project_dir": PROJECT,
        "python_path": "python",
        **overrides,
    }


@pytest.fixture
def compose_application(admin, server, tmp_path) -> Application:
    backups = tmp_path / "host" / "backups"
    backups.mkdir(parents=True)
    return make_application(
        admin,
        name="shop",
        server=server,
        kind="compose",
        engine="docker",
        compose_service="backend",
        compose_files=["compose.yaml", "compose.prod.yaml"],
        project_dir=PROJECT,
        python_path="python",
        remote_backup_dir="/app/backups",
        mounts=[
            {
                "type": "bind",
                "source": str(backups),
                "destination": "/app/backups",
                "rw": True,
            }
        ],
        backup_passphrase=BACKUP_PASSPHRASE,
    )


@pytest.mark.django_db
def test_a_compose_application_is_added_with_its_service_and_files(api, server):
    response = api.post(APPLICATIONS, compose_settings(server), format="json")

    assert response.status_code == 201
    body = response.json()
    assert (
        body["kind"],
        body["engine"],
        body["compose_service"],
        body["compose_files"],
    ) == ("compose", "docker", "backend", ["compose.yaml", "compose.prod.yaml"])
    assert body["project_dir"] == PROJECT


@pytest.mark.django_db
def test_a_podman_compose_application_names_its_project(api, server):
    body = api.post(
        APPLICATIONS,
        compose_settings(server, engine="podman", compose_project="shop"),
        format="json",
    ).json()

    assert (body["engine"], body["compose_project"]) == ("podman", "shop")


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("overrides", "errors"),
    [
        ({"compose_service": ""}, {"compose_service": ["compose_service_required"]}),
        ({"project_dir": ""}, {"project_dir": ["compose_folder_required"]}),
        ({"engine": ""}, {"engine": ["engine_required"]}),
        ({"compose_service": "-d"}, {"compose_service": ["invalid"]}),
        ({"compose_service": "web; rm"}, {"compose_service": ["invalid"]}),
        ({"compose_project": "-p"}, {"compose_project": ["invalid"]}),
        ({"compose_files": ["../other/compose.yaml"]}, {"compose_files": ["invalid"]}),
        ({"compose_files": ["-p"]}, {"compose_files": ["invalid"]}),
        ({"kind": "kubernetes"}, {"kind": ["invalid_choice"]}),
        ({"engine": "lxc"}, {"engine": ["invalid_choice"]}),
    ],
)
def test_a_compose_application_needs_an_engine_a_service_and_a_folder(
    api, server, overrides, errors
):
    response = api.post(
        APPLICATIONS, compose_settings(server, **overrides), format="json"
    )

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == errors
    assert not Application.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("overrides", "errors"),
    [
        ({"container_name": ""}, {"container_name": ["container_required"]}),
        ({"container_name": "-it"}, {"container_name": ["invalid"]}),
        ({"container_name": "web; id"}, {"container_name": ["invalid"]}),
        ({"engine": ""}, {"engine": ["engine_required"]}),
    ],
)
def test_a_container_application_needs_an_engine_and_its_container(
    api, server, overrides, errors
):
    settings = {
        "server": str(server.pk),
        "name": "blog",
        "kind": "container",
        "engine": "docker",
        "container_name": "blog-web-1",
        **overrides,
    }

    response = api.post(APPLICATIONS, settings, format="json")

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == errors


@pytest.mark.django_db
def test_switching_to_compose_later_needs_the_engine_and_the_service(
    api, admin, application
):
    response = api.patch(
        detail(application),
        {"kind": "compose", "account_password": "x"},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {
        "engine": ["engine_required"],
        "compose_service": ["compose_service_required"],
    }


@pytest.mark.django_db
def test_a_check_asks_the_engine_and_the_service(
    api, compose_application, monkeypatch, tmp_path
):
    host = connected_to(monkeypatch, ComposeHost(tmp_path / "container"))

    body = api.post(detail(compose_application, "check/")).json()

    assert body["last_check_status"] == "ok"
    report = body["last_check_report"]
    assert report["container"] == {
        "engine": "docker",
        "version": COMPOSE_VERSION,
        "error": "",
        "running": True,
    }
    assert report["dbs_version"] == REMOTE_DBS_VERSION
    assert report["backup_command"] is True
    argvs = [run["argv"] for run in host.runs]
    assert [
        "docker",
        "compose",
        "-f",
        "compose.yaml",
        "-f",
        "compose.prod.yaml",
        "exec",
        "-T",
        "backend",
        "python",
        "-c",
        VERSION_PROBE,
    ] in argvs
    assert [
        "docker",
        "compose",
        "-f",
        "compose.yaml",
        "-f",
        "compose.prod.yaml",
        "ps",
        "--status",
        "running",
        "--services",
    ] in argvs
    assert body["last_health"] == {"status": "ok", "checks": []}
    assert body["compatible"] is True


@pytest.mark.django_db
def test_a_path_a_mount_maps_is_looked_for_on_the_host_and_others_inside(
    api, admin, compose_application, monkeypatch, tmp_path
):
    host = connected_to(monkeypatch, ComposeHost(tmp_path / "container"))
    host.inside("/app/media").mkdir(parents=True)
    ApplicationRepository().update(
        compose_application,
        file_roots=["/app/media", "/app/static"],
        env_path="/app/.env",
        env_location=Application.EnvLocation.CONTAINER,
    )

    report = api.post(detail(compose_application, "check/")).json()["last_check_report"]

    assert report["remote_backup_dir"] is True
    assert report["roots"] == {"/app/media": True, "/app/static": False}
    assert report["env_file"] is False
    looked_inside = [
        run["argv"][-1] for run in host.runs if run["argv"][-3:-2] == ["-c"]
    ]
    assert "/app/backups" not in looked_inside
    assert {"/app/media", "/app/static", "/app/.env"} <= set(looked_inside)


@pytest.mark.django_db
def test_a_check_learns_whether_commands_can_be_stopped_inside_the_service(
    admin, compose_application, monkeypatch, tmp_path
):
    host = connected_to(monkeypatch, ComposeHost(tmp_path / "container"))

    checked = ApplicationService(admin).check(compose_application.pk)

    probe = [
        run["argv"]
        for run in host.runs
        if run["argv"][-5:] == ["timeout", "-k", "1", "5", "true"]
    ]
    assert probe and probe[0][:2] == ["docker", "compose"]
    assert checked.timeout_in_container is False


@pytest.mark.django_db
def test_a_stopped_service_needs_attention(
    api, compose_application, monkeypatch, tmp_path
):
    connected_to(monkeypatch, ComposeHost(tmp_path / "container", running=("db",)))

    body = api.post(detail(compose_application, "check/")).json()

    assert body["last_check_status"] == "problem"
    assert body["last_check_report"]["container"]["running"] is False
    assert body["last_check_report"]["dbs_version"] is None
    assert (
        ApplicationRepository().get(compose_application.pk).timeout_in_container is None
    )


@pytest.mark.django_db
def test_a_server_without_the_engine_says_so(
    api, compose_application, monkeypatch, tmp_path
):
    connected_to(monkeypatch, ComposeHost(tmp_path / "container", docker=False))

    body = api.post(detail(compose_application, "check/")).json()

    assert body["last_check_status"] == "problem"
    assert body["last_check_report"]["container"] == {
        "engine": "docker",
        "version": None,
        "error": "sh: 1: docker: not found",
        "running": False,
    }


@pytest.mark.django_db
def test_the_passphrase_is_read_from_inside_the_service(
    admin, compose_application, monkeypatch, tmp_path
):
    host = connected_to(monkeypatch, ComposeHost(tmp_path / "container"))

    ApplicationService(admin).capture_passphrase(compose_application.pk)

    [run] = host.runs
    assert run["argv"][-4:] == ["python", "manage.py", "dbs_key", "--show"]
    assert "backend" in run["argv"]
    stored = ApplicationRepository().get(compose_application.pk)
    assert ServerConnectionService(admin).backup_passphrase(stored) == (
        "derived-passphrase-from-the-container"
    )
