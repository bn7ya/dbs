from __future__ import annotations

import pytest

from dbs.manager.servers.models import Server
from dbs.manager.servers.services import ServerService, discovery_service
from dbs.manager.servers.services.discovery_service import discovered_settings
from dbs.manager.servers.services.pythons import VERSION_PROBE
from tests.manager.servers.compose import COMPOSE_VERSION, ComposeHost, connected_to
from tests.manager.servers.support import BACKUP_PASSPHRASE, KEY_PASSPHRASE

SERVERS = "/api/servers/"
PROJECT = "/srv/shop"


def detail(server, action=""):
    return f"{SERVERS}{server.pk}/{action}"


def compose_settings(host_key, private_key, **overrides):
    return {
        "name": "shop",
        "host": "shop.example.com",
        "username": "deploy",
        "auth_method": "key",
        "private_key": private_key,
        "key_passphrase": KEY_PASSPHRASE,
        "backup_passphrase": BACKUP_PASSPHRASE,
        "host_key": host_key,
        "runtime": "compose",
        "compose_service": "backend",
        "compose_files": ["compose.yaml", "compose.prod.yaml"],
        "project_dir": PROJECT,
        "python_path": "python",
        **overrides,
    }


@pytest.fixture
def compose_server(admin, host_key, private_key, tmp_path) -> Server:
    data = compose_settings(host_key, private_key)
    data.pop("key_passphrase")
    backups = tmp_path / "host" / "backups"
    backups.mkdir(parents=True)
    return ServerService(admin).create(**data, remote_backup_dir=str(backups))


@pytest.fixture
def new_server(admin, host_key, private_key) -> Server:
    data = compose_settings(host_key, private_key, name="new")
    for name in ("key_passphrase", "runtime", "compose_service", "compose_files"):
        data.pop(name)
    return ServerService(admin).create(**data)


@pytest.mark.django_db
def test_a_compose_server_is_added_with_its_service_and_files(
    api, host_key, private_key
):
    response = api.post(SERVERS, compose_settings(host_key, private_key), format="json")

    assert response.status_code == 201
    body = response.json()
    assert (body["runtime"], body["compose_service"], body["compose_files"]) == (
        "compose",
        "backend",
        ["compose.yaml", "compose.prod.yaml"],
    )
    assert body["project_dir"] == PROJECT


@pytest.mark.django_db
def test_a_server_added_without_a_runtime_runs_on_the_host(api, host_key, private_key):
    data = compose_settings(host_key, private_key)
    for name in ("runtime", "compose_service", "compose_files"):
        data.pop(name)

    body = api.post(SERVERS, data, format="json").json()

    assert (body["runtime"], body["compose_service"], body["compose_files"]) == (
        "host",
        "",
        [],
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("overrides", "errors"),
    [
        ({"compose_service": ""}, {"compose_service": ["compose_service_required"]}),
        ({"project_dir": ""}, {"project_dir": ["compose_folder_required"]}),
        ({"compose_service": "-d"}, {"compose_service": ["invalid"]}),
        ({"compose_service": "web; rm"}, {"compose_service": ["invalid"]}),
        ({"compose_files": ["../other/compose.yaml"]}, {"compose_files": ["invalid"]}),
        ({"compose_files": ["-p"]}, {"compose_files": ["invalid"]}),
        ({"runtime": "kubernetes"}, {"runtime": ["invalid_choice"]}),
    ],
)
def test_a_compose_server_needs_a_service_and_a_folder(
    api, host_key, private_key, overrides, errors
):
    response = api.post(
        SERVERS, compose_settings(host_key, private_key, **overrides), format="json"
    )

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == errors
    assert not Server.objects.exists()


@pytest.mark.django_db
def test_switching_to_compose_later_needs_the_service(api, configured_server):
    response = api.patch(
        detail(configured_server), {"runtime": "compose"}, format="json"
    )

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {
        "compose_service": ["compose_service_required"]
    }


@pytest.mark.django_db
def test_a_check_asks_docker_and_the_service(
    api, compose_server, monkeypatch, tmp_path
):
    host = connected_to(monkeypatch, ComposeHost(tmp_path / "container"))

    body = api.post(detail(compose_server, "check/")).json()

    assert body["last_check_status"] == "ok"
    report = body["last_check_report"]
    assert report["compose"] == {
        "version": COMPOSE_VERSION,
        "error": "",
        "running": True,
    }
    assert report["dbs_version"] == "0.5.0"
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
    assert body["last_health"] == {"status": "ok", "checks": []}


@pytest.mark.django_db
def test_a_stopped_service_needs_attention(api, compose_server, monkeypatch, tmp_path):
    connected_to(monkeypatch, ComposeHost(tmp_path / "container", running=("db",)))

    body = api.post(detail(compose_server, "check/")).json()

    assert body["last_check_status"] == "problem"
    assert body["last_check_report"]["compose"]["running"] is False
    assert body["last_check_report"]["dbs_version"] is None


@pytest.mark.django_db
def test_a_server_without_docker_says_so(api, compose_server, monkeypatch, tmp_path):
    connected_to(monkeypatch, ComposeHost(tmp_path / "container", docker=False))

    body = api.post(detail(compose_server, "check/")).json()

    assert body["last_check_status"] == "problem"
    assert body["last_check_report"]["compose"] == {
        "version": None,
        "error": "sh: 1: docker: not found",
        "running": False,
    }


@pytest.mark.django_db
def test_the_passphrase_is_read_from_inside_the_service(
    api, compose_server, monkeypatch, tmp_path
):
    host = connected_to(monkeypatch, ComposeHost(tmp_path / "container"))

    ServerService(compose_server.created_by).capture_passphrase(compose_server.pk)

    [run] = host.runs
    assert run["argv"][-4:] == ["python", "manage.py", "dbs_key", "--show"]
    assert "backend" in run["argv"]


@pytest.mark.django_db
def test_discovery_finds_the_service_that_has_django_dbs(
    api, new_server, monkeypatch, tmp_path
):
    shop = tmp_path / "shop"
    (shop / "backend").mkdir(parents=True)
    (shop / "compose.yaml").write_text("services: {}")
    (shop / "backend" / "manage.py").write_text("")
    (shop / ".env").write_text("SECRET=1")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(discovery_service, "SEARCH_ROOTS", ("~",))
    connected_to(monkeypatch, ComposeHost(tmp_path / "container"))

    body = api.post(detail(new_server, "discover/")).json()

    assert body["runtime"] == "compose"
    assert body["compose_service"] == "backend"
    assert body["project_dir"] == str(shop)
    assert body["python_path"] == "python3"
    assert body["env_path"] == str(shop / ".env")
    assert body["dbs_version"] == "0.5.0"
    assert body["candidates"]["compose_services"] == ["db", "backend"]
    assert body["candidates"]["project_dirs"][0] == str(shop)


@pytest.mark.django_db
def test_discovery_falls_back_to_the_host_when_no_service_has_django_dbs(
    api, new_server, monkeypatch, tmp_path
):
    shop = tmp_path / "shop"
    shop.mkdir()
    (shop / "compose.yaml").write_text("services: {}")
    (shop / "manage.py").write_text("")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(discovery_service, "SEARCH_ROOTS", ("~",))
    connected_to(monkeypatch, ComposeHost(tmp_path / "container", with_dbs=()))

    body = api.post(detail(new_server, "discover/")).json()

    assert body["runtime"] == "host"
    assert body["project_dir"] == str(shop)


@pytest.mark.django_db
def test_discovery_skips_a_compose_folder_others_can_write_to(
    api, new_server, monkeypatch, tmp_path
):
    shop = tmp_path / "shop"
    (shop / "backend").mkdir(parents=True)
    (shop / "compose.yaml").write_text("services: {}")
    (shop / "backend" / "manage.py").write_text("")
    shop.chmod(0o777)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(discovery_service, "SEARCH_ROOTS", ("~",))
    host = connected_to(monkeypatch, ComposeHost(tmp_path / "container"))

    body = api.post(detail(new_server, "discover/")).json()

    assert body["runtime"] == "host"
    assert not [run for run in host.runs if "compose" in run["argv"]]


def test_a_runtime_discovery_did_not_confirm_is_left_alone():
    unconfirmed = {"runtime": "host", "project_dir": "/srv/shop", "dbs_version": None}
    confirmed = {
        **unconfirmed,
        "runtime": "compose",
        "compose_service": "web",
        "dbs_version": "0.5.0",
    }

    assert "runtime" not in discovered_settings(unconfirmed, chosen=True)
    assert discovered_settings(confirmed, chosen=True)["runtime"] == "compose"
    assert discovered_settings(confirmed, chosen=True)["compose_service"] == "web"
