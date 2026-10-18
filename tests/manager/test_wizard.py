import base64
import hashlib
import json
import os
import re
from datetime import timedelta

import pytest
from django.utils import timezone

import dbs
from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.applications.models import Application
from dbs.manager.applications.repositories import ApplicationRepository
from dbs.manager.applications.services import discovery_service
from dbs.manager.servers.gateways import parse_host_key
from dbs.manager.servers.models import Server
from dbs.manager.servers.repositories import ServerRepository
from dbs.manager.servers.services import ServerConnectionService
from tests.manager.factories import make_application, make_server
from tests.manager.remote import scripted_hosts
from tests.manager.servers.support import (
    BACKUP_PASSPHRASE,
    DBS_VERSION,
    ENV_PATH,
    MEDIA_ROOT,
    PASSWORD,
    PROJECT_DIR,
    PYTHON,
    FakeRemote,
    Result,
    connecting_to,
    host_key_line,
)
from tests.manager.support import logged

SERVERS = "/api/servers/"
APPLICATIONS = "/api/applications/"
DISCOVER = f"{APPLICATIONS}discover/"
CONNECT = "dbs.manager.servers.services.connection_service.connect"
FETCH_HOST_KEY = "dbs.manager.servers.services.server_service.fetch_host_key"
FINGERPRINT = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")
HEALTH = {
    "status": "warn",
    "checks": [{"name": "backup age", "status": "warn", "message": "2 days old"}],
    "last_backup_at": "2026-10-07T03:00:00Z",
    "generated_at": "2026-10-09T03:00:00Z",
}


def server_url(server, action=""):
    return f"{SERVERS}{server.pk}/{action}"


def url(application, action=""):
    return f"{APPLICATIONS}{application.pk}/{action}"


def create(admin, **fields):
    values = {
        "project_dir": PROJECT_DIR,
        "python_path": PYTHON,
        "backup_passphrase": BACKUP_PASSPHRASE,
    }
    return make_application(admin, **{**values, **fields})


@pytest.mark.django_db
def test_a_fingerprint_reads_as_openssh_prints_it(api, monkeypatch):
    line = host_key_line()
    monkeypatch.setattr(FETCH_HOST_KEY, lambda host, port: parse_host_key(line))

    body = api.post(f"{SERVERS}fingerprint/", {"host": "10.0.0.9", "port": 22}).json()

    blob = base64.b64decode(line.split()[1])
    expected = "SHA256:" + base64.b64encode(
        hashlib.sha256(blob).digest()
    ).decode().rstrip("=")
    assert body["fingerprint"] == expected
    assert FINGERPRINT.match(body["fingerprint"])


@pytest.mark.django_db
def test_a_server_added_with_a_generated_key_shows_its_public_half(api, admin):
    response = api.post(
        SERVERS,
        {
            "name": "web-1",
            "host": "10.0.0.5",
            "username": "deploy",
            "host_key": host_key_line(),
            "generate_key": True,
        },
        format="json",
    )

    assert response.status_code == 201
    body = response.json()
    public_key = body["public_key"]
    assert public_key.startswith("ssh-ed25519 ") and public_key.endswith(" django-dbs")
    assert body["authorized_keys_hint"] == (
        f"echo '{public_key}' >> ~deploy/.ssh/authorized_keys"
    )
    assert (body["auth_method"], body["has_private_key"]) == ("key", True)
    assert "private_key" not in body
    server = ServerRepository().get(body["id"])
    assert (
        "OPENSSH PRIVATE KEY"
        in ServerConnectionService(admin).credentials(server).private_key
    )
    [entry] = logged("server.keypair")
    assert entry.subject == body["id"]
    assert FINGERPRINT.match(entry.data["fingerprint"])
    assert api.get(f"{SERVERS}{body['id']}/public-key/").json() == {
        "public_key": public_key
    }


@pytest.mark.django_db
def test_a_server_without_a_key_choice_is_refused(api):
    response = api.post(
        SERVERS,
        {
            "name": "web-1",
            "host": "10.0.0.5",
            "username": "deploy",
            "host_key": host_key_line(),
        },
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["fields"]["auth_method"] == ["required"]


@pytest.mark.django_db
def test_the_public_key_is_derived_from_a_pasted_private_key(api, admin):
    server = make_server(admin)

    public_key = api.get(server_url(server, "public-key/")).json()["public_key"]

    assert public_key.startswith("ssh-ed25519 AAAA")


@pytest.mark.django_db
def test_a_password_server_has_no_public_key(api, admin):
    server = make_server(
        admin,
        auth_method=Server.AuthMethod.PASSWORD,
        private_key="",
        password="secret-1",
    )

    response = api.get(server_url(server, "public-key/"))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_private_key"


@pytest.mark.django_db
def test_a_new_servers_address_can_be_corrected_for_an_hour(api, admin):
    fresh = make_server(admin)
    older = make_server(admin, name="web-2")
    ServerRepository().update(older, created_at=timezone.now() - timedelta(hours=2))

    corrected = api.patch(server_url(fresh), {"host": "10.0.0.9"}, format="json")
    guarded = api.patch(server_url(older), {"host": "10.0.0.9"}, format="json")

    assert corrected.status_code == 200
    assert corrected.json()["host"] == "10.0.0.9"
    assert guarded.status_code == 400
    assert guarded.json()["error"]["fields"] == {"account_password": ["required"]}


@pytest.mark.django_db
def test_paths_found_while_adding_an_application_need_no_password_for_an_hour(
    api, admin
):
    application = create(admin)
    paths = {"project_dir": "/srv/found", "python_path": "/srv/found/.venv/bin/python"}

    allowed = api.patch(
        url(application), {**paths, "file_roots": [MEDIA_ROOT]}, format="json"
    )
    reached = api.patch(
        url(application), {"backup_passphrase": "another-passphrase"}, format="json"
    )

    assert allowed.status_code == 200
    assert allowed.json()["project_dir"] == "/srv/found"
    assert allowed.json()["file_roots"] == [MEDIA_ROOT]
    assert reached.status_code == 400
    assert reached.json()["error"]["fields"] == {"account_password": ["required"]}


@pytest.mark.django_db
def test_a_wrong_password_is_refused_even_where_none_is_needed(api, admin):
    application = create(admin)

    response = api.patch(
        url(application),
        {"project_dir": "/srv/found", "account_password": "not-the-password"},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_password"
    application.refresh_from_db()
    assert application.project_dir != "/srv/found"


@pytest.mark.django_db
def test_after_an_hour_a_check_or_for_someone_else_paths_need_the_password(api, admin):
    older = create(admin)
    ApplicationRepository().update(
        older, created_at=timezone.now() - timedelta(hours=2)
    )
    other = UserRepository().create(username="omar", password=PASSWORD)
    theirs = create(other, name="web-2", host="10.0.0.6")
    checked = create(admin, name="web-3", host="10.0.0.7")
    ApplicationRepository().update(
        checked,
        last_checked_at=timezone.now(),
        last_check_status=Application.CheckStatus.OK,
    )

    for application in (older, theirs, checked):
        response = api.patch(
            url(application), {"project_dir": "/srv/found"}, format="json"
        )
        assert response.status_code == 400
        assert response.json()["error"]["fields"] == {"account_password": ["required"]}


@pytest.mark.django_db
def test_a_check_that_did_not_pass_leaves_the_paths_open_to_fix(api, admin):
    application = create(admin)
    ApplicationRepository().update(
        application,
        last_checked_at=timezone.now(),
        last_check_status=Application.CheckStatus.PROBLEM,
    )

    response = api.patch(
        url(application), {"python_path": "/srv/app/venv/bin/python"}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["python_path"] == "/srv/app/venv/bin/python"


@pytest.fixture
def project(tmp_path, monkeypatch):
    home = tmp_path / "home"
    app = home / "app"
    (app / ".venv" / "bin").mkdir(parents=True)
    (app / ".venv" / "bin" / "python").write_text("")
    (app / "manage.py").write_text(
        "import os\n"
        "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shop.settings.prod')\n"
    )
    (app / ".env").write_text("SECRET_KEY=x\n")
    (home / ".cache" / "hidden").mkdir(parents=True)
    (home / ".cache" / "hidden" / "manage.py").write_text("")
    sites = tmp_path / "srv" / "sites"
    other = sites / "blog"
    other.mkdir(parents=True)
    (other / "manage.py").write_text("")
    (tmp_path / "srv" / "a" / "b" / "c").mkdir(parents=True)
    (tmp_path / "srv" / "a" / "b" / "c" / "manage.py").write_text("")
    monkeypatch.chdir(home)
    monkeypatch.setattr(discovery_service, "SEARCH_ROOTS", ("~", str(tmp_path / "srv")))
    return {"home": home, "app": app, "sites": sites, "blog": other}


def discovered(api, server, folder=""):
    response = api.post(
        DISCOVER, {"server": str(server.pk), "folder": folder}, format="json"
    )
    assert response.status_code == 200, response.json()
    return response.json()


@pytest.mark.django_db
def test_discovery_without_a_folder_lists_the_folders_that_hold_a_project(
    api, admin, project, monkeypatch
):
    server = make_server(admin)
    hosts = scripted_hosts(monkeypatch)

    body = discovered(api, server)

    assert body == {
        "folder": "",
        "trusted": False,
        "listing": {},
        "engines": {},
        "candidates": [],
        "folders": [str(project["app"]), str(project["blog"])],
    }
    assert hosts.runs("10.0.0.5") == []


@pytest.mark.django_db
def test_discovery_finds_the_project_over_sftp(api, admin, project, monkeypatch):
    server = make_server(admin)
    hosts = scripted_hosts(monkeypatch)
    app = str(project["app"])

    body = discovered(api, server, app)

    assert (body["folder"], body["trusted"]) == (app, True)
    assert body["listing"] == {
        "manage": True,
        "compose_files": [],
        "container_files": [],
        "env_files": [".env"],
    }
    assert {
        engine: facts["installed"] for engine, facts in body["engines"].items()
    } == {
        "docker": False,
        "podman": False,
    }
    [candidate] = body["candidates"]
    assert {
        key: candidate[key]
        for key in (
            "kind",
            "engine",
            "project_dir",
            "python_path",
            "python_paths",
            "manage_path",
            "settings_module",
            "env",
            "dbs_version",
            "compatible",
            "problems",
        )
    } == {
        "kind": "host",
        "engine": "",
        "project_dir": app,
        "python_path": f"{app}/.venv/bin/python",
        "python_paths": [f"{app}/.venv/bin/python", "python3", "python"],
        "manage_path": "manage.py",
        "settings_module": "shop.settings.prod",
        "env": [{"path": f"{app}/.env", "location": "host", "source": "folder"}],
        "dbs_version": None,
        "compatible": False,
        "problems": ["dbs_missing"],
    }
    assert [run["argv"][:2] for run in hosts.runs("10.0.0.5")][-3:] == [
        [f"{app}/.venv/bin/python", "-c"],
        ["python3", "-c"],
        ["python", "-c"],
    ]
    [entry] = logged("application.discover")
    assert (entry.subject, entry.target_name, entry.status) == (
        str(server.pk),
        app,
        "succeeded",
    )
    assert entry.data == {"folder": app, "candidates": 1}


@pytest.mark.django_db
def test_discovery_prefers_what_the_project_says_about_itself(
    api, admin, project, monkeypatch
):
    server = make_server(admin)
    hosts = scripted_hosts(monkeypatch)
    app = str(project["app"])
    python = f"{app}/.venv/bin/python"
    details = {
        "dbs_connection": 1,
        "hostname": "web-1",
        "ssh_user": "deploy",
        "project_dir": app,
        "python_path": "/opt/py/bin/python",
        "manage_path": "manage.py",
        "settings_module": "shop.settings.live",
        "remote_backup_dir": "/var/backups/shop",
        "file_roots": ["/srv/media"],
        "env_path": "/etc/shop.env",
        "dbs_version": "0.7.1",
        "host_keys": [{"type": "ssh-ed25519", "fingerprint": "SHA256:abc"}],
    }
    hosts.answer("10.0.0.5", [python, "-c", DBS_VERSION], (0, "0.7.1\n", ""))
    hosts.answer(
        "10.0.0.5",
        [python, "manage.py", "dbs", "connection", "--json"],
        (0, json.dumps(details), ""),
    )

    [candidate] = discovered(api, server, app)["candidates"]

    assert candidate["python_path"] == python
    assert candidate["settings_module"] == "shop.settings.live"
    assert candidate["remote_backup_dir"] == "/var/backups/shop"
    assert candidate["backup_dir_on_host"] == "/var/backups/shop"
    assert candidate["file_roots"] == [{"path": "/srv/media", "on_host": "/srv/media"}]
    assert candidate["env"] == [
        {"path": "/etc/shop.env", "location": "host", "source": "dbs"},
        {"path": f"{app}/.env", "location": "host", "source": "folder"},
    ]
    assert (candidate["dbs_version"], candidate["compatible"]) == ("0.7.1", True)
    assert candidate["problems"] == []
    assert hosts.runs("10.0.0.5")[-1]["setup"] == [
        f"cd {app} || exit 1",
        "export DJANGO_SETTINGS_MODULE=shop.settings.prod",
    ]


@pytest.mark.django_db
def test_an_application_added_from_a_candidate_keeps_what_discovery_found(
    api, admin, project, monkeypatch
):
    server = make_server(admin)
    hosts = scripted_hosts(monkeypatch)
    app = str(project["app"])
    python = f"{app}/.venv/bin/python"
    hosts.answer("10.0.0.5", [python, "-c", DBS_VERSION], (0, "0.7.1\n", ""))
    [candidate] = discovered(api, server, app)["candidates"]

    response = api.post(
        APPLICATIONS,
        {
            "server": str(server.pk),
            "discovered": True,
            **discovery_service.settings_of(candidate, "shop"),
        },
        format="json",
    )

    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["server"]["id"] == str(server.pk)
    assert (body["name"], body["kind"], body["engine"]) == ("shop", "host", "")
    assert (body["project_dir"], body["python_path"]) == (app, python)
    assert body["settings_module"] == "shop.settings.prod"
    assert (body["env_path"], body["env_location"]) == (f"{app}/.env", "host")
    assert body["has_backup_passphrase"] is True
    assert body["discovered_at"] is not None
    [entry] = logged("application.create")
    assert entry.subject == body["id"]


@pytest.mark.django_db
def test_discovery_finds_a_virtualenv_of_any_name_that_has_django_dbs(
    api, admin, project, monkeypatch
):
    server = make_server(admin)
    app = project["app"]
    (app / "shop-env" / "bin").mkdir(parents=True)
    (app / "shop-env" / "pyvenv.cfg").write_text("home = /usr/bin\n")
    hosts = scripted_hosts(monkeypatch)
    venv = f"{app}/shop-env/bin/python"
    hosts.answer("10.0.0.5", [venv, "-c", DBS_VERSION], (0, "0.7.0\n", ""))

    [candidate] = discovered(api, server, str(app))["candidates"]

    assert candidate["python_path"] == venv
    assert candidate["dbs_version"] == "0.7.0"
    assert candidate["python_paths"] == [
        f"{app}/.venv/bin/python",
        venv,
        "python3",
        "python",
    ]
    assert hosts.runs("10.0.0.5")[-1]["argv"][:3] == [venv, "manage.py", "dbs"]


@pytest.mark.django_db
def test_discovery_of_a_folder_without_a_project_looks_one_level_down(
    api, admin, project, monkeypatch
):
    server = make_server(admin)
    hosts = scripted_hosts(monkeypatch)
    hosts.answer("10.0.0.5", ["python3", "-c", DBS_VERSION], (0, "0.7.0\n", ""))
    blog = str(project["blog"])

    body = discovered(api, server, str(project["sites"]))

    assert body["listing"]["manage"] is False
    [candidate] = body["candidates"]
    assert candidate["project_dir"] == blog
    assert candidate["python_path"] == "python3"
    assert (candidate["dbs_version"], candidate["compatible"]) == ("0.7.0", True)


@pytest.mark.django_db
def test_a_django_dbs_older_than_the_manager_needs_is_named(
    api, admin, project, monkeypatch
):
    server = make_server(admin)
    hosts = scripted_hosts(monkeypatch)
    app = str(project["app"])
    hosts.answer(
        "10.0.0.5",
        [f"{app}/.venv/bin/python", "-c", DBS_VERSION],
        (0, "0.5.0\n", ""),
    )

    [candidate] = discovered(api, server, app)["candidates"]

    assert candidate["dbs_version"] == "0.5.0"
    assert candidate["compatible"] is False
    assert candidate["problems"] == ["dbs_too_old"]


@pytest.mark.django_db
def test_discovery_runs_nothing_in_a_folder_anyone_may_change(
    api, admin, project, monkeypatch
):
    server = make_server(admin)
    hosts = scripted_hosts(monkeypatch)
    app = project["app"]
    os.chmod(app, 0o777)

    body = discovered(api, server, str(app))

    assert (body["trusted"], body["candidates"], body["engines"]) == (False, [], {})
    assert body["listing"]["manage"] is True
    assert hosts.runs("10.0.0.5") == []


@pytest.mark.django_db
def test_discovery_refuses_a_relative_folder(api, admin, monkeypatch):
    server = make_server(admin)
    scripted_hosts(monkeypatch)

    response = api.post(
        DISCOVER, {"server": str(server.pk), "folder": "srv/app"}, format="json"
    )

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"folder": ["absolute_path_required"]}
    assert logged("application.discover") == []


@pytest.mark.django_db
def test_searching_a_server_after_its_first_hour_needs_the_password(
    api, admin, project, monkeypatch
):
    server = make_server(admin)
    ServerRepository().update(server, created_at=timezone.now() - timedelta(hours=2))
    scripted_hosts(monkeypatch)
    app = str(project["app"])

    refused = api.post(
        DISCOVER, {"server": str(server.pk), "folder": app}, format="json"
    )
    allowed = api.post(
        DISCOVER,
        {"server": str(server.pk), "folder": app, "account_password": PASSWORD},
        format="json",
    )

    assert refused.status_code == 400
    assert refused.json()["error"]["fields"] == {"account_password": ["required"]}
    assert allowed.status_code == 200
    assert len(allowed.json()["candidates"]) == 1


@pytest.mark.django_db
def test_the_passphrase_is_captured_from_the_application_and_sealed(
    api, admin, monkeypatch
):
    application = create(admin, settings_module="shop.settings")
    hosts = scripted_hosts(monkeypatch)
    hosts.answer(
        "10.0.0.5",
        [PYTHON, "manage.py", "dbs_key", "--show"],
        (0, "derived-remote-passphrase\n", "Store this somewhere safe."),
    )

    response = api.post(url(application, "passphrase/capture/"))

    assert response.status_code == 200
    assert response.json() == {"captured": True}
    application.refresh_from_db()
    assert ServerConnectionService(admin).backup_passphrase(application) == (
        "derived-remote-passphrase"
    )
    [run] = hosts.runs("10.0.0.5")
    assert run["stdin"] is None
    [entry] = logged("application.passphrase_capture")
    assert entry.subject == str(application.pk)
    assert "derived-remote-passphrase" not in json.dumps([entry.data, entry.detail])


@pytest.mark.django_db
def test_a_capture_that_fails_keeps_the_stored_passphrase(api, admin, monkeypatch):
    application = create(admin)
    hosts = scripted_hosts(monkeypatch)
    hosts.answer(
        "10.0.0.5", [PYTHON, "manage.py", "dbs_key", "--show"], (1, "", "boom")
    )

    response = api.post(url(application, "passphrase/capture/"))

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "remote_command_failed"
    application.refresh_from_db()
    assert (
        ServerConnectionService(admin).backup_passphrase(application)
        == BACKUP_PASSPHRASE
    )
    assert logged("application.passphrase_capture")[0].status == "failed"


def remote_with(version, health=None):
    answers = {
        ("uname", "-sr"): Result(0, "Linux 6.1\n"),
        (PYTHON, "-c", DBS_VERSION): Result(0, f"{version}\n"),
        (PYTHON, "manage.py", "dbs_backup", "--help"): Result(0, "usage\n"),
    }
    if health is not None:
        answers[(PYTHON, "manage.py", "dbs", "health", "--json")] = Result(0, health)
    return FakeRemote(answers=answers, paths={ENV_PATH, MEDIA_ROOT, "/var/backups/dbs"})


@pytest.mark.django_db
def test_a_check_compares_versions_and_reads_health(api, admin, monkeypatch):
    application = create(admin)
    remote = remote_with("0.7.1", json.dumps(HEALTH))
    monkeypatch.setattr(CONNECT, connecting_to(remote))

    body = api.post(url(application, "check/")).json()

    assert body["local_version"] == dbs.__version__
    assert (body["remote_version"], body["compatible"]) == ("0.7.1", True)
    assert body["last_health"] == HEALTH
    assert body["last_check_status"] == "ok"
    assert ApplicationRepository().get(application.pk).last_health == HEALTH


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("version", "compatible"), [("0.7.0", True), ("0.6.9", False), ("0.4.0", False)]
)
def test_every_installed_version_is_asked_for_its_health(
    api, admin, monkeypatch, version, compatible
):
    application = create(admin)
    remote = remote_with(version)
    monkeypatch.setattr(CONNECT, connecting_to(remote))

    body = api.post(url(application, "check/")).json()

    assert (body["remote_version"], body["compatible"]) == (version, compatible)
    assert body["last_health"] is None
    assert [run["argv"][2:4] for run in remote.runs].count(["dbs", "health"]) == 1


@pytest.mark.django_db
def test_health_that_is_not_the_documented_json_is_ignored(api, admin, monkeypatch):
    application = create(admin)
    monkeypatch.setattr(CONNECT, connecting_to(remote_with("0.7.0", "not json")))

    assert api.post(url(application, "check/")).json()["last_health"] is None
