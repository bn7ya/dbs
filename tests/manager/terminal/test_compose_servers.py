from __future__ import annotations

import pytest

from dbs.manager.adapters.checks import problem
from dbs.manager.servers.gateways import parse_host_key
from dbs.manager.servers.models import Server
from dbs.manager.servers.repositories import ServerRepository
from tests.manager.servers.compose import ComposeHost, connected_to
from tests.manager.servers.support import SSH_PASSWORD, host_key_line

FETCH_HOST_KEY = "dbs.manager.servers.services.server_service.fetch_host_key"


@pytest.fixture
def offered(monkeypatch):
    line = host_key_line()
    monkeypatch.setattr(FETCH_HOST_KEY, lambda host, port: parse_host_key(line))
    return line


@pytest.fixture
def docker_host(monkeypatch, tmp_path):
    backups = tmp_path / "host" / "backups"
    backups.mkdir(parents=True)
    host = connected_to(monkeypatch, ComposeHost(tmp_path / "container"))
    host.backups = str(backups)
    return host


@pytest.mark.django_db
def test_add_a_compose_server_from_the_terminal_and_check_it(
    terminal, admin, offered, docker_host
):
    ran = terminal(
        "server",
        "add",
        "shop",
        "--host",
        "10.0.0.7",
        "--user",
        "deploy",
        "--ssh-password-stdin",
        "--runtime",
        "compose",
        "--compose-service",
        "backend",
        "--compose-file",
        "compose.yaml",
        "--compose-file",
        "compose.prod.yaml",
        "--project-dir",
        "/srv/shop",
        "--python",
        "python",
        "--backup-dir",
        docker_host.backups,
        "--no-discover",
        "--yes",
        stdin=f"{SSH_PASSWORD}\n",
    )

    assert ran.code == 0, ran.err
    server = ServerRepository().active().get(name="shop")
    assert server.runtime == Server.Runtime.COMPOSE
    assert server.compose_service == "backend"
    assert server.compose_files == ["compose.yaml", "compose.prod.yaml"]
    assert server.last_check_status == Server.CheckStatus.OK

    shown = terminal("server", "show", "shop")
    assert "compose" in shown.out and "backend" in shown.out


@pytest.mark.django_db
def test_a_compose_server_needs_its_service_from_the_terminal_too(
    terminal, admin, offered, docker_host
):
    ran = terminal(
        "server",
        "add",
        "shop",
        "--host",
        "10.0.0.7",
        "--user",
        "deploy",
        "--ssh-password-stdin",
        "--runtime",
        "compose",
        "--project-dir",
        "/srv/shop",
        "--no-discover",
        "--yes",
        stdin=f"{SSH_PASSWORD}\n",
    )

    assert ran.code != 0
    assert "compose service: Name the Docker Compose service" in ran.err
    assert not ServerRepository().active().exists()


def compose_server(**report) -> Server:
    return Server(
        name="shop",
        username="deploy",
        runtime=Server.Runtime.COMPOSE,
        compose_service="backend",
        python_path="python",
        remote_backup_dir="/var/backups/dbs",
        last_check_status=Server.CheckStatus.PROBLEM,
        last_check_report={
            "dbs_version": None,
            "backup_command": False,
            "remote_backup_dir": True,
            **report,
        },
    )


def test_a_stopped_service_is_the_one_problem_reported():
    server = compose_server(
        compose={"version": "2.29.1", "error": "", "running": False}
    )

    assert problem(server) == "the backend service is not running"


def test_docker_that_does_not_run_says_why():
    server = compose_server(
        compose={
            "version": None,
            "error": "permission denied while trying to connect to the Docker daemon socket",
            "running": False,
        }
    )

    assert problem(server) == (
        "docker compose does not run for deploy (permission denied while trying "
        "to connect to the Docker daemon socket)"
    )


def test_a_service_without_django_dbs_names_the_service():
    server = compose_server(
        compose={"version": "2.29.1", "error": "", "running": True},
        backup_command=None,
    )

    assert (
        problem(server)
        == "django-dbs is not installed for python in the backend service"
    )
