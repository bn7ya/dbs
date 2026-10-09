from __future__ import annotations

import pytest

from dbs.manager.servers.exceptions import (
    HostKeyChanged,
    RemoteCommandFailed,
    SSHAuthFailed,
    SSHUnreachable,
)
from dbs.manager.servers.gateways import parse_host_key
from dbs.manager.servers.models import Server
from dbs.manager.servers.services import ServerService
from dbs.manager.servers.services.server_service import DBS_VERSION
from tests.manager.servers.support import (
    BACKUP_DIR,
    BACKUP_PASSPHRASE,
    ENV_PATH,
    KEY_PASSPHRASE,
    MEDIA_ROOT,
    PASSWORD,
    PROJECT_DIR,
    PYTHON,
    SETTINGS_MODULE,
    FakeRemote,
    Result,
    connecting_to,
    healthy_remote,
    host_key_line,
    refusing_with,
)

CONNECT = "dbs.manager.servers.services.connection_service.connect"
FETCH_HOST_KEY = "dbs.manager.servers.services.server_service.fetch_host_key"


def check(server_id) -> str:
    return f"/api/servers/{server_id}/check/"


def repin(server_id) -> str:
    return f"/api/servers/{server_id}/host-key/"


def passphrase(server_id) -> str:
    return f"/api/servers/{server_id}/passphrase/"


@pytest.mark.django_db
def test_the_fingerprint_is_read_from_the_server(api, monkeypatch, host_key):
    asked = []

    def presented(host, port):
        asked.append((host, port))
        return parse_host_key(host_key)

    monkeypatch.setattr(FETCH_HOST_KEY, presented)

    response = api.post("/api/servers/fingerprint/", {"host": "web-1.example.com"})

    assert response.status_code == 200
    assert asked == [("web-1.example.com", 22)]
    body = response.json()
    assert body["key_type"] == "ssh-ed25519"
    assert body["line"] == host_key
    assert body["fingerprint"] == parse_host_key(host_key).fingerprint


@pytest.mark.django_db
def test_an_unreachable_server_has_no_fingerprint(api, monkeypatch):
    def unreachable(host, port):
        raise SSHUnreachable()

    monkeypatch.setattr(FETCH_HOST_KEY, unreachable)

    response = api.post("/api/servers/fingerprint/", {"host": "10.0.0.9", "port": 2222})

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "ssh_unreachable"


@pytest.mark.django_db
def test_a_server_with_everything_in_place_is_ok(
    api, monkeypatch, configured_server, private_key, host_key
):
    remote = healthy_remote()
    monkeypatch.setattr(CONNECT, connecting_to(remote))

    response = api.post(check(configured_server.pk))

    assert response.status_code == 200
    body = response.json()
    assert body["last_check_status"] == "ok"
    assert body["last_check_error"] == ""
    assert body["last_checked_at"] is not None
    assert body["last_check_report"] == {
        "system": "Linux 6.1.0-18-amd64",
        "dbs_version": "0.4.0",
        "backup_command": True,
        "env_file": True,
        "roots": {MEDIA_ROOT: True},
        "remote_backup_dir": True,
    }
    assert remote.credentials.private_key == private_key
    assert remote.credentials.key_passphrase == KEY_PASSPHRASE
    assert remote.credentials.password is None
    assert (remote.credentials.host, remote.credentials.port) == ("10.0.0.5", 2222)
    assert remote.credentials.host_key == host_key
    assert remote.credentials.remote_dir == BACKUP_DIR


@pytest.mark.django_db
def test_the_check_runs_argv_lists_in_the_project(api, monkeypatch, configured_server):
    remote = healthy_remote()
    monkeypatch.setattr(CONNECT, connecting_to(remote))

    api.post(check(configured_server.pk))

    assert remote.runs == [
        {"argv": ["uname", "-sr"], "cwd": None, "env": None},
        {"argv": [PYTHON, "-c", DBS_VERSION], "cwd": PROJECT_DIR, "env": None},
        {
            "argv": [PYTHON, "manage.py", "dbs_backup", "--help"],
            "cwd": PROJECT_DIR,
            "env": {"DJANGO_SETTINGS_MODULE": SETTINGS_MODULE},
        },
    ]


@pytest.mark.django_db
def test_something_configured_but_missing_is_a_problem(
    api, monkeypatch, configured_server
):
    remote = healthy_remote()
    remote.paths -= {ENV_PATH, MEDIA_ROOT}
    remote.answers = {
        **remote.answers,
        (PYTHON, "-c", DBS_VERSION): RemoteCommandFailed(),
    }
    monkeypatch.setattr(CONNECT, connecting_to(remote))

    body = api.post(check(configured_server.pk)).json()

    assert body["last_check_status"] == "problem"
    report = body["last_check_report"]
    assert report["dbs_version"] is None
    assert report["env_file"] is False
    assert report["roots"] == {MEDIA_ROOT: False}
    assert report["backup_command"] is True


@pytest.mark.django_db
def test_a_probe_that_fails_marks_only_its_own_item(
    api, monkeypatch, configured_server
):
    remote = FakeRemote(
        answers={
            ("uname", "-sr"): Result(0, "\n"),
            (PYTHON, "-c", DBS_VERSION): Result(
                1, "", "ModuleNotFoundError: No module named 'dbs'"
            ),
            (PYTHON, "manage.py", "dbs_backup", "--help"): RemoteCommandFailed(),
        },
        paths={ENV_PATH, MEDIA_ROOT},
        unreadable=frozenset({BACKUP_DIR}),
    )
    monkeypatch.setattr(CONNECT, connecting_to(remote))

    body = api.post(check(configured_server.pk)).json()

    assert body["last_check_status"] == "problem"
    assert body["last_check_report"] == {
        "system": None,
        "dbs_version": None,
        "backup_command": False,
        "env_file": True,
        "roots": {MEDIA_ROOT: True},
        "remote_backup_dir": False,
    }


@pytest.mark.django_db
def test_what_is_not_configured_is_not_looked_at(api, admin, monkeypatch, host_key):
    server = ServerService(admin).create(
        name="bare",
        host="10.0.0.6",
        username="deploy",
        auth_method=Server.AuthMethod.PASSWORD,
        password="ssh-password",
        host_key=host_key,
    )
    remote = healthy_remote()
    remote.answers = {
        ("uname", "-sr"): remote.answers[("uname", "-sr")],
        ("python3", "-c", DBS_VERSION): remote.answers[(PYTHON, "-c", DBS_VERSION)],
    }
    monkeypatch.setattr(CONNECT, connecting_to(remote))

    body = api.post(check(server.pk)).json()

    assert body["last_check_status"] == "ok"
    assert body["last_check_report"] == {
        "system": "Linux 6.1.0-18-amd64",
        "dbs_version": "0.4.0",
        "backup_command": None,
        "env_file": None,
        "roots": {},
        "remote_backup_dir": True,
    }
    assert remote.credentials.password == "ssh-password"
    assert remote.credentials.private_key is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (HostKeyChanged(), 409, "host_key_changed"),
        (SSHAuthFailed(), 400, "ssh_auth_failed"),
        (SSHUnreachable(), 502, "ssh_unreachable"),
    ],
)
def test_a_connection_that_fails_is_stored_and_reported(
    api, monkeypatch, configured_server, error, status, code
):
    monkeypatch.setattr(CONNECT, refusing_with(error))

    response = api.post(check(configured_server.pk))

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    stored = api.get(f"/api/servers/{configured_server.pk}/").json()
    assert stored["last_check_status"] == "failed"
    assert stored["last_check_error"] == code
    assert stored["last_checked_at"] is not None
    assert stored["last_check_report"] == {}


@pytest.mark.django_db
def test_checking_a_deleted_server_is_not_found(api, monkeypatch, configured_server):
    monkeypatch.setattr(CONNECT, connecting_to(healthy_remote()))
    api.delete(f"/api/servers/{configured_server.pk}/")

    assert api.post(check(configured_server.pk)).status_code == 404


@pytest.mark.django_db
def test_a_new_host_key_needs_the_users_password(api, configured_server, host_key):
    response = api.post(
        repin(configured_server.pk), {"host_key": host_key_line(), "password": "wrong"}
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_password"
    assert (
        api.get(f"/api/servers/{configured_server.pk}/").json()["host_key"] == host_key
    )


@pytest.mark.django_db
def test_a_new_host_key_is_pinned_and_the_status_reset(
    api, monkeypatch, configured_server
):
    monkeypatch.setattr(CONNECT, refusing_with(HostKeyChanged()))
    api.post(check(configured_server.pk))
    replacement = host_key_line()

    response = api.post(
        repin(configured_server.pk), {"host_key": replacement, "password": PASSWORD}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["host_key"] == replacement
    assert body["host_key_fingerprint"] == parse_host_key(replacement).fingerprint
    assert body["last_check_status"] == "unknown"
    assert body["last_check_error"] == ""


@pytest.mark.django_db
def test_a_new_host_key_must_be_one(api, configured_server):
    response = api.post(
        repin(configured_server.pk), {"host_key": "not a key", "password": PASSWORD}
    )

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"host_key": ["invalid_host_key"]}


@pytest.mark.django_db
def test_the_passphrase_needs_the_users_password(api, configured_server):
    response = api.post(passphrase(configured_server.pk), {"password": "wrong"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_password"
    assert BACKUP_PASSPHRASE not in response.content.decode()


@pytest.mark.django_db
def test_the_passphrase_is_shown_and_never_cached(api, configured_server):
    response = api.post(passphrase(configured_server.pk), {"password": PASSWORD})

    assert response.status_code == 200
    assert response.json() == {"passphrase": BACKUP_PASSPHRASE}
    assert response["Cache-Control"] == "no-store"


@pytest.mark.django_db
def test_an_empty_passphrase_is_generated(api, admin, host_key):
    server = ServerService(admin).create(
        name="generated",
        host="10.0.0.7",
        username="deploy",
        auth_method=Server.AuthMethod.PASSWORD,
        password="ssh-password",
        host_key=host_key,
        backup_passphrase="",
    )

    shown = api.post(passphrase(server.pk), {"password": PASSWORD}).json()["passphrase"]

    assert len(shown) >= 40
