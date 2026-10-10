import base64
import hashlib
import json
import re
from datetime import timedelta

import pytest
from django.utils import timezone

import dbs
from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.servers.gateways import parse_host_key
from dbs.manager.servers.models import Server
from dbs.manager.servers.repositories import ServerRepository
from dbs.manager.servers.services import (
    ServerConnectionService,
    ServerService,
    discovery_service,
)
from dbs.manager.servers.services.server_service import DBS_VERSION
from tests.manager.remote import scripted_hosts
from tests.manager.servers.support import (
    BACKUP_PASSPHRASE,
    ENV_PATH,
    MEDIA_ROOT,
    PASSWORD,
    PROJECT_DIR,
    PYTHON,
    FakeRemote,
    Result,
    connecting_to,
    host_key_line,
    private_key_text,
)
from tests.manager.support import logged

SERVERS = "/api/servers/"
CONNECT = "dbs.manager.servers.services.connection_service.connect"
FETCH_HOST_KEY = "dbs.manager.servers.services.server_service.fetch_host_key"
FINGERPRINT = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")
HEALTH = {
    "status": "warn",
    "checks": [{"name": "backup age", "status": "warn", "message": "2 days old"}],
    "last_backup_at": "2026-10-07T03:00:00Z",
    "generated_at": "2026-10-09T03:00:00Z",
}


def url(server, action=""):
    return f"{SERVERS}{server.pk}/{action}"


def create(admin, **fields):
    values = {
        "name": "web-1",
        "host": "10.0.0.5",
        "username": "deploy",
        "auth_method": Server.AuthMethod.KEY,
        "private_key": private_key_text(),
        "host_key": host_key_line(),
        "project_dir": PROJECT_DIR,
        "python_path": PYTHON,
        "backup_passphrase": BACKUP_PASSPHRASE,
    }
    return ServerService(admin).create(**{**values, **fields})


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
    server = create(admin)

    public_key = api.get(url(server, "public-key/")).json()["public_key"]

    assert public_key.startswith("ssh-ed25519 AAAA")


@pytest.mark.django_db
def test_a_password_server_has_no_public_key(api, admin):
    server = create(
        admin,
        auth_method=Server.AuthMethod.PASSWORD,
        private_key="",
        password="secret-1",
    )

    response = api.get(url(server, "public-key/"))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_private_key"


@pytest.mark.django_db
def test_paths_found_while_adding_a_server_need_no_password_for_an_hour(api, admin):
    server = create(admin)
    paths = {"project_dir": "/srv/found", "python_path": "/srv/found/.venv/bin/python"}

    allowed = api.patch(
        url(server), {**paths, "file_roots": [MEDIA_ROOT]}, format="json"
    )
    reached = api.patch(url(server), {"host": "10.0.0.9"}, format="json")

    assert allowed.status_code == 200
    assert allowed.json()["project_dir"] == "/srv/found"
    assert reached.status_code == 400
    assert reached.json()["error"]["fields"] == {"account_password": ["required"]}


@pytest.mark.django_db
def test_a_wrong_password_is_refused_even_where_none_is_needed(api, admin):
    server = create(admin)

    response = api.patch(
        url(server),
        {"project_dir": "/srv/found", "account_password": "not-the-password"},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_password"
    server.refresh_from_db()
    assert server.project_dir != "/srv/found"


@pytest.mark.django_db
def test_after_an_hour_a_check_or_for_someone_else_paths_need_the_password(api, admin):
    older = create(admin)
    ServerRepository().update(older, created_at=timezone.now() - timedelta(hours=2))
    other = UserRepository().create(username="omar", password=PASSWORD)
    theirs = create(other, name="web-2")
    checked = create(admin, name="web-3")
    ServerRepository().update(
        checked,
        last_checked_at=timezone.now(),
        last_check_status=Server.CheckStatus.OK,
    )

    for server in (older, theirs, checked):
        response = api.patch(url(server), {"project_dir": "/srv/found"}, format="json")
        assert response.status_code == 400
        assert response.json()["error"]["fields"] == {"account_password": ["required"]}


@pytest.mark.django_db
def test_a_check_that_did_not_pass_leaves_the_paths_open_to_fix(api, admin):
    server = create(admin)
    ServerRepository().update(
        server,
        last_checked_at=timezone.now(),
        last_check_status=Server.CheckStatus.PROBLEM,
    )

    response = api.patch(
        url(server), {"python_path": "/srv/app/venv/bin/python"}, format="json"
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
    other = tmp_path / "srv" / "sites" / "blog"
    other.mkdir(parents=True)
    (other / "manage.py").write_text("")
    (tmp_path / "srv" / "a" / "b" / "c").mkdir(parents=True)
    (tmp_path / "srv" / "a" / "b" / "c" / "manage.py").write_text("")
    monkeypatch.chdir(home)
    monkeypatch.setattr(discovery_service, "SEARCH_ROOTS", ("~", str(tmp_path / "srv")))
    return {"home": home, "app": app, "blog": other}


@pytest.mark.django_db
def test_discovery_finds_the_project_over_sftp(api, admin, project, monkeypatch):
    server = create(admin)
    hosts = scripted_hosts(monkeypatch)

    response = api.post(url(server, "discover/"))

    assert response.status_code == 200
    app = str(project["app"])
    assert response.json() == {
        "project_dir": app,
        "python_path": f"{app}/.venv/bin/python",
        "manage_path": "manage.py",
        "settings_module": "shop.settings.prod",
        "remote_backup_dir": server.remote_backup_dir,
        "file_roots": [],
        "env_path": f"{app}/.env",
        "dbs_version": None,
        "is_project": True,
        "candidates": {
            "project_dirs": [app, str(project["blog"])],
            "python_paths": [f"{app}/.venv/bin/python", "python3", "python"],
        },
    }
    assert hosts.runs("10.0.0.5")[-1]["argv"] == [
        f"{app}/.venv/bin/python",
        "manage.py",
        "dbs",
        "connection",
        "--json",
    ]
    [entry] = logged("server.discover")
    assert entry.subject == str(server.pk) and entry.status == "succeeded"


@pytest.mark.django_db
def test_discovery_prefers_what_the_project_says_about_itself(
    api, admin, project, monkeypatch
):
    server = create(admin)
    hosts = scripted_hosts(monkeypatch)
    app = str(project["app"])
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
        "dbs_version": "0.5.0",
        "host_keys": [{"type": "ssh-ed25519", "fingerprint": "SHA256:abc"}],
    }
    hosts.answer(
        "10.0.0.5",
        [f"{app}/.venv/bin/python", "manage.py", "dbs", "connection", "--json"],
        (0, json.dumps(details), ""),
    )

    body = api.post(url(server, "discover/")).json()

    assert body["python_path"] == "/opt/py/bin/python"
    assert body["settings_module"] == "shop.settings.live"
    assert body["remote_backup_dir"] == "/var/backups/shop"
    assert body["file_roots"] == ["/srv/media"]
    assert body["env_path"] == "/etc/shop.env"
    assert body["dbs_version"] == "0.5.0"
    assert hosts.runs("10.0.0.5")[-1]["setup"][-1].endswith("shop.settings.prod")


@pytest.mark.django_db
def test_discovery_with_no_project_suggests_defaults(api, admin, tmp_path, monkeypatch):
    server = create(admin)
    scripted_hosts(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(discovery_service, "SEARCH_ROOTS", ("~",))

    body = api.post(url(server, "discover/")).json()

    assert body["project_dir"] == "" and body["python_path"] == "python3"
    assert body["candidates"] == {
        "project_dirs": [],
        "python_paths": ["python3", "python"],
    }


@pytest.mark.django_db
def test_discovery_finds_a_virtualenv_of_any_name_that_has_django_dbs(
    api, admin, project, monkeypatch
):
    server = create(admin)
    app = project["app"]
    (app / "shop-env" / "bin").mkdir(parents=True)
    (app / "shop-env" / "pyvenv.cfg").write_text("home = /usr/bin\n")
    hosts = scripted_hosts(monkeypatch)
    venv = f"{app}/shop-env/bin/python"
    hosts.answer("10.0.0.5", [venv, "-c", DBS_VERSION], (0, "0.5.0\n", ""))

    body = api.post(url(server, "discover/")).json()

    assert body["python_path"] == venv
    assert body["dbs_version"] == "0.5.0"
    assert body["candidates"]["python_paths"] == [
        f"{app}/.venv/bin/python",
        venv,
        "python3",
        "python",
    ]
    assert hosts.runs("10.0.0.5")[-1]["argv"][:3] == [venv, "manage.py", "dbs"]


@pytest.mark.django_db
def test_discovery_of_a_chosen_folder_skips_the_search(
    api, admin, project, monkeypatch
):
    server = create(admin)
    hosts = scripted_hosts(monkeypatch)
    blog = str(project["blog"])
    hosts.answer("10.0.0.5", ["python3", "-c", DBS_VERSION], (0, "0.5.0\n", ""))

    body = api.post(url(server, "discover/"), {"project_dir": blog}).json()

    assert body["project_dir"] == blog
    assert body["is_project"] is True
    assert body["python_path"] == "python3"
    assert body["dbs_version"] == "0.5.0"
    assert body["candidates"]["project_dirs"] == [blog]


@pytest.mark.django_db
def test_discovery_refuses_a_relative_folder(api, admin, monkeypatch):
    server = create(admin)
    scripted_hosts(monkeypatch)

    response = api.post(url(server, "discover/"), {"project_dir": "srv/app"})

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {
        "project_dir": ["absolute_path_required"]
    }


@pytest.mark.django_db
def test_the_passphrase_is_captured_from_the_server_and_sealed(api, admin, monkeypatch):
    server = create(admin, settings_module="shop.settings")
    hosts = scripted_hosts(monkeypatch)
    hosts.answer(
        "10.0.0.5",
        [PYTHON, "manage.py", "dbs_key", "--show"],
        (0, "derived-remote-passphrase\n", "Store this somewhere safe."),
    )

    response = api.post(url(server, "passphrase/capture/"))

    assert response.status_code == 200
    assert response.json() == {"captured": True}
    server.refresh_from_db()
    assert ServerConnectionService(admin).backup_passphrase(server) == (
        "derived-remote-passphrase"
    )
    [run] = hosts.runs("10.0.0.5")
    assert run["stdin"] is None
    [entry] = logged("server.passphrase_capture")
    assert entry.subject == str(server.pk)
    assert "derived-remote-passphrase" not in json.dumps([entry.data, entry.detail])


@pytest.mark.django_db
def test_a_capture_that_fails_keeps_the_stored_passphrase(api, admin, monkeypatch):
    server = create(admin)
    hosts = scripted_hosts(monkeypatch)
    hosts.answer(
        "10.0.0.5", [PYTHON, "manage.py", "dbs_key", "--show"], (1, "", "boom")
    )

    response = api.post(url(server, "passphrase/capture/"))

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "remote_command_failed"
    server.refresh_from_db()
    assert ServerConnectionService(admin).backup_passphrase(server) == BACKUP_PASSPHRASE
    assert logged("server.passphrase_capture")[0].status == "failed"


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
def test_a_check_compares_versions_and_reads_health_from_0_5(api, admin, monkeypatch):
    server = create(admin)
    remote = remote_with("0.5.1", json.dumps(HEALTH))
    monkeypatch.setattr(CONNECT, connecting_to(remote))

    body = api.post(url(server, "check/")).json()

    assert body["local_version"] == dbs.__version__
    assert (body["remote_version"], body["compatible"]) == ("0.5.1", True)
    assert body["last_health"] == HEALTH
    assert body["last_check_status"] == "ok"
    assert ServerRepository().get(server.pk).last_health == HEALTH


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("version", "compatible"), [("0.4.0", True), ("0.2.2", True), ("0.2.1", False)]
)
def test_an_older_server_is_checked_without_health(
    api, admin, monkeypatch, version, compatible
):
    server = create(admin)
    remote = remote_with(version)
    monkeypatch.setattr(CONNECT, connecting_to(remote))

    body = api.post(url(server, "check/")).json()

    assert (body["remote_version"], body["compatible"]) == (version, compatible)
    assert body["last_health"] is None
    assert all(run["argv"][2:4] != ["dbs", "health"] for run in remote.runs)


@pytest.mark.django_db
def test_health_that_is_not_the_documented_json_is_ignored(api, admin, monkeypatch):
    server = create(admin)
    monkeypatch.setattr(CONNECT, connecting_to(remote_with("0.5.0", "not json")))

    assert api.post(url(server, "check/")).json()["last_health"] is None
