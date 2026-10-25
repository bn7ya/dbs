from __future__ import annotations

import pytest

from dbs.manager.servers.exceptions import (
    HostKeyChanged,
    RemoteCommandFailed,
    RemoteCommandTimedOut,
    ServerConnectionLost,
    SSHAuthFailed,
    SSHUnreachable,
)
from dbs.manager.servers.gateways import parse_host_key
from dbs.manager.servers.models import Server
from dbs.manager.servers.repositories import ServerRepository
from dbs.manager.servers.services import ServerService
from tests.manager.servers.support import (
    KEY_PASSPHRASE,
    PASSWORD,
    FakeRemote,
    Result,
    connecting_to,
    host_key_line,
    refusing_with,
)
from tests.manager.support import logged

CONNECT = "dbs.manager.servers.services.connection_service.connect"
FETCH_HOST_KEY = "dbs.manager.servers.services.server_service.fetch_host_key"
UNAME = ("uname", "-sr")
DOCKER_VERSION = ("docker", "version", "--format", "{{.Server.Version}}")
DOCKER_COMPOSE = ("docker", "compose", "version", "--short")
PODMAN_VERSION = ("podman", "version", "--format", "{{.Version}}")
PODMAN_COMPOSE = ("podman", "compose", "version", "--short")
TIMEOUT_PROBE = ("timeout", "-k", "1", "5", "true")
DOCKER_SOCKET_REFUSED = (
    "permission denied while trying to connect to the Docker daemon socket at "
    'unix:///var/run/docker.sock: Get "http://%2Fvar%2Frun%2Fdocker.sock/v1.47/'
    'version": dial unix /var/run/docker.sock: connect: permission denied'
)
DOCKER_API_REFUSED = (
    "failed to connect to the docker API at unix:///var/run/docker.sock; check if "
    "the path is correct and if the daemon is running: dial unix "
    "/var/run/docker.sock: connect: permission denied"
)
DOCKER_API_MISSING = (
    "failed to connect to the docker API at unix:///var/run/docker.sock; check if "
    "the path is correct and if the daemon is running: dial unix "
    "/var/run/docker.sock: connect: no such file or directory"
)
PODMAN_SOCKET_REFUSED = (
    "Error: unable to connect to Podman socket: Get "
    '"http://d/v5.2.2/libpod/_ping": dial unix /run/podman/podman.sock: '
    "connect: permission denied"
)
ABSENT = {
    "installed": False,
    "usable": False,
    "version": None,
    "compose": None,
    "error": "",
}


def check(server_id) -> str:
    return f"/api/servers/{server_id}/check/"


def repin(server_id) -> str:
    return f"/api/servers/{server_id}/host-key/"


def host(answers=None) -> FakeRemote:
    return FakeRemote(
        answers={
            UNAME: Result(0, "Linux 6.1.0-18-amd64\n"),
            DOCKER_VERSION: Result(0, "27.3.1\n"),
            DOCKER_COMPOSE: Result(0, "2.29.7\n"),
            PODMAN_VERSION: Result(127, "", "sh: 1: podman: not found"),
            TIMEOUT_PROBE: Result(0),
            **(answers or {}),
        },
        paths=set(),
    )


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
def test_a_server_that_answers_is_ok_and_reports_its_system_and_engines(
    api, monkeypatch, configured_server, private_key, host_key
):
    remote = host()
    monkeypatch.setattr(CONNECT, connecting_to(remote))

    response = api.post(check(configured_server.pk))

    assert response.status_code == 200
    body = response.json()
    assert body["last_check_status"] == "ok"
    assert body["last_check_error"] == ""
    assert body["last_checked_at"] is not None
    docker = {
        "installed": True,
        "usable": True,
        "version": "27.3.1",
        "compose": "2.29.7",
        "error": "",
    }
    assert body["engines"] == {"docker": docker, "podman": ABSENT}
    assert body["last_check_report"] == {
        "system": "Linux 6.1.0-18-amd64",
        "engines": {"docker": docker, "podman": ABSENT},
        "timeout": True,
    }
    assert body["timeout_on_host"] is True
    assert remote.credentials.private_key == private_key
    assert remote.credentials.key_passphrase == KEY_PASSPHRASE
    assert remote.credentials.password is None
    assert (remote.credentials.host, remote.credentials.port) == ("10.0.0.5", 2222)
    assert remote.credentials.host_key == host_key


@pytest.mark.django_db
def test_the_check_runs_fixed_argv_lists_and_nothing_in_a_project(
    api, monkeypatch, configured_server
):
    remote = host()
    monkeypatch.setattr(CONNECT, connecting_to(remote))

    api.post(check(configured_server.pk))

    assert remote.runs == [
        {"argv": list(UNAME), "cwd": None, "env": None},
        {"argv": list(DOCKER_VERSION), "cwd": None, "env": None},
        {"argv": list(DOCKER_COMPOSE), "cwd": None, "env": None},
        {"argv": list(PODMAN_VERSION), "cwd": None, "env": None},
        {"argv": list(TIMEOUT_PROBE), "cwd": None, "env": None},
    ]


@pytest.mark.django_db
def test_podman_with_its_compose_is_reported_beside_docker(
    api, monkeypatch, configured_server
):
    remote = host(
        {
            DOCKER_VERSION: Result(127, "", "sh: 1: docker: not found"),
            PODMAN_VERSION: Result(0, "5.2.2\n"),
            PODMAN_COMPOSE: Result(0, "podman-compose version 1.2.0\n"),
        }
    )
    monkeypatch.setattr(CONNECT, connecting_to(remote))

    engines = api.post(check(configured_server.pk)).json()["engines"]

    assert engines == {
        "docker": ABSENT,
        "podman": {
            "installed": True,
            "usable": True,
            "version": "5.2.2",
            "compose": "podman-compose version 1.2.0",
            "error": "",
        },
    }


@pytest.mark.django_db
@pytest.mark.parametrize("refused", [DOCKER_SOCKET_REFUSED, DOCKER_API_REFUSED])
def test_an_engine_whose_socket_refuses_the_user_is_installed_but_not_usable(
    api, monkeypatch, configured_server, refused
):
    remote = host({DOCKER_VERSION: Result(1, "Client: 27.3.1\n", refused)})
    monkeypatch.setattr(CONNECT, connecting_to(remote))

    body = api.post(check(configured_server.pk)).json()

    assert body["engines"]["docker"] == {
        "installed": True,
        "usable": False,
        "version": None,
        "compose": None,
        "error": "engine_permission_denied",
    }
    assert body["last_check_status"] == "ok"
    assert list(DOCKER_COMPOSE) not in [run["argv"] for run in remote.runs]


@pytest.mark.django_db
def test_an_engine_that_fails_otherwise_keeps_the_last_line_it_printed(
    api, monkeypatch, configured_server
):
    remote = host(
        {
            DOCKER_VERSION: Result(
                1, "Client: Docker Engine - Community\n", f"{DOCKER_API_MISSING}\n"
            )
        }
    )
    monkeypatch.setattr(CONNECT, connecting_to(remote))

    docker = api.post(check(configured_server.pk)).json()["engines"]["docker"]

    assert (docker["installed"], docker["usable"]) == (True, False)
    assert docker["error"] == DOCKER_API_MISSING[:200]


@pytest.mark.django_db
def test_a_rootful_podman_socket_that_refuses_the_user_is_named_too(
    api, monkeypatch, configured_server
):
    remote = host({PODMAN_VERSION: Result(125, "", PODMAN_SOCKET_REFUSED)})
    monkeypatch.setattr(CONNECT, connecting_to(remote))

    podman = api.post(check(configured_server.pk)).json()["engines"]["podman"]

    assert (podman["installed"], podman["usable"], podman["error"]) == (
        True,
        False,
        "engine_permission_denied",
    )


@pytest.mark.django_db
def test_an_engine_that_is_not_installed_exits_127_and_is_absent(
    api, monkeypatch, configured_server
):
    remote = host({DOCKER_VERSION: Result(127, "", "sh: 1: docker: not found")})
    monkeypatch.setattr(CONNECT, connecting_to(remote))

    engines = api.post(check(configured_server.pk)).json()["engines"]

    assert engines == {"docker": ABSENT, "podman": ABSENT}


@pytest.mark.django_db
def test_an_engine_without_compose_has_no_compose_version(
    api, monkeypatch, configured_server
):
    remote = host(
        {DOCKER_COMPOSE: Result(1, "", "docker: 'compose' is not a docker command.")}
    )
    monkeypatch.setattr(CONNECT, connecting_to(remote))

    docker = api.post(check(configured_server.pk)).json()["engines"]["docker"]

    assert (docker["usable"], docker["version"], docker["compose"]) == (
        True,
        "27.3.1",
        None,
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("probe", "error", "status", "code"),
    [
        (PODMAN_VERSION, ServerConnectionLost(), 502, "connection_lost"),
        (DOCKER_COMPOSE, RemoteCommandTimedOut(), 504, "remote_command_timed_out"),
        (UNAME, RemoteCommandFailed(), 502, "remote_command_failed"),
        (TIMEOUT_PROBE, ServerConnectionLost(), 502, "connection_lost"),
    ],
)
def test_a_probe_that_cannot_run_fails_the_check_and_keeps_what_was_known(
    api, monkeypatch, configured_server, probe, error, status, code
):
    monkeypatch.setattr(CONNECT, connecting_to(host()))
    found = api.post(check(configured_server.pk)).json()["engines"]
    monkeypatch.setattr(CONNECT, connecting_to(host({probe: error})))

    response = api.post(check(configured_server.pk))

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    kept = ServerRepository().get(configured_server.pk)
    assert (kept.last_check_status, kept.last_check_error) == (
        Server.CheckStatus.FAILED,
        code,
    )
    assert kept.engines == found


@pytest.mark.django_db
def test_a_server_that_does_not_name_its_system_needs_attention(
    api, monkeypatch, configured_server
):
    remote = host({UNAME: Result(0, "\n"), TIMEOUT_PROBE: Result(127)})
    monkeypatch.setattr(CONNECT, connecting_to(remote))

    body = api.post(check(configured_server.pk)).json()

    assert body["last_check_status"] == "problem"
    assert body["last_check_report"]["system"] is None
    assert body["last_check_report"]["timeout"] is False
    assert body["timeout_on_host"] is False


@pytest.mark.django_db
def test_a_check_is_logged_with_its_status(api, monkeypatch, configured_server):
    monkeypatch.setattr(CONNECT, connecting_to(host()))

    api.post(check(configured_server.pk))

    [entry] = logged("server.check")
    assert (entry.status, entry.subject, entry.data) == (
        "succeeded",
        str(configured_server.pk),
        {"status": "ok"},
    )


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
def test_a_failed_check_keeps_the_engines_the_last_one_found(
    api, monkeypatch, configured_server
):
    monkeypatch.setattr(CONNECT, connecting_to(host()))
    found = api.post(check(configured_server.pk)).json()["engines"]
    monkeypatch.setattr(CONNECT, refusing_with(SSHUnreachable()))

    api.post(check(configured_server.pk))

    kept = ServerRepository().get(configured_server.pk)
    assert kept.last_check_status == Server.CheckStatus.FAILED
    assert kept.engines == found


@pytest.mark.django_db
def test_checking_a_deleted_server_is_not_found(api, monkeypatch, configured_server):
    monkeypatch.setattr(CONNECT, connecting_to(host()))
    api.delete(
        f"/api/servers/{configured_server.pk}/",
        {"account_password": PASSWORD},
        format="json",
    )

    assert api.post(check(configured_server.pk)).status_code == 404


@pytest.mark.django_db
def test_a_check_through_the_service_returns_the_server(
    admin, monkeypatch, configured_server
):
    monkeypatch.setattr(CONNECT, connecting_to(host()))

    checked = ServerService(admin).check(configured_server.pk)

    assert isinstance(checked, Server)
    assert checked.pk == configured_server.pk
    assert checked.engines["docker"]["version"] == "27.3.1"


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
