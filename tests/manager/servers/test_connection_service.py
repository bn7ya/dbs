from __future__ import annotations

from uuid import uuid4

import pytest
from rest_framework.exceptions import NotFound

from dbs.manager.applications.repositories import ApplicationRepository
from dbs.manager.applications.services import ApplicationService
from dbs.manager.servers.gateways import ContainerTarget, DbsProfile
from dbs.manager.servers.services import ServerConnectionService, ServerService
from dbs.manager.servers.services.connection_service import container_of
from tests.manager.factories import make_application
from tests.manager.servers.support import (
    BACKUP_DIR,
    HOME,
    PASSWORD,
    PROJECT_DIR,
    PYTHON,
    SETTINGS_MODULE,
    connecting_to,
    healthy_remote,
)

CONNECT = "dbs.manager.servers.services.connection_service.connect"


@pytest.fixture
def compose_application(admin, configured_server):
    return make_application(
        admin,
        name="shop",
        server=configured_server,
        kind="compose",
        engine="podman",
        compose_project="shop",
        compose_service="backend",
        compose_files=["compose.yaml", "compose.prod.yaml"],
        project_dir="/srv/shop",
        workdir="/app",
        python_path="/opt/venv/bin/python",
        manage_path="/app/manage.py",
        settings_module="shop.settings",
        remote_backup_dir="/app/backups",
    )


@pytest.fixture
def container_application(admin, configured_server):
    return make_application(
        admin,
        name="blog",
        server=configured_server,
        kind="container",
        engine="docker",
        container_name="blog-web-1",
        workdir="/code",
        python_path="python",
        remote_backup_dir="/code/backups",
    )


@pytest.mark.django_db
@pytest.mark.parametrize("by_id", [True, False])
def test_a_server_opens_by_row_or_by_id(admin, monkeypatch, configured_server, by_id):
    remote = healthy_remote()
    monkeypatch.setattr(CONNECT, connecting_to(remote))
    target = configured_server.pk if by_id else configured_server

    with ServerConnectionService(admin).open(target) as opened:
        assert opened is remote

    assert remote.credentials.host == configured_server.host


@pytest.mark.django_db
def test_an_application_opens_the_server_it_runs_on(
    admin, monkeypatch, configured_application
):
    remote = healthy_remote()
    monkeypatch.setattr(CONNECT, connecting_to(remote))

    with ServerConnectionService(admin).open(configured_application) as opened:
        assert opened is remote

    server = configured_application.server
    assert (remote.credentials.host, remote.credentials.port) == (
        server.host,
        server.port,
    )
    assert remote.credentials.host_key == server.host_key


@pytest.mark.django_db
def test_an_unknown_or_deleted_server_does_not_open(
    admin, monkeypatch, configured_server
):
    monkeypatch.setattr(CONNECT, connecting_to(healthy_remote()))
    ServerService(admin).delete(configured_server.pk, account_password=PASSWORD)
    connections = ServerConnectionService(admin)

    for server_id in (configured_server.pk, uuid4()):
        with pytest.raises(NotFound), connections.open(server_id):
            pass


@pytest.mark.django_db
def test_a_dbs_profile_says_where_and_how_manage_py_runs(admin, configured_application):
    connections = ServerConnectionService(admin)

    configured = connections.dbs_profile(configured_application)
    bare = connections.dbs_profile(
        ApplicationService(admin).update(
            configured_application.pk,
            account_password=PASSWORD,
            project_dir="",
            settings_module="",
        )
    )

    assert configured == DbsProfile(
        python=PYTHON,
        manage="manage.py",
        project_dir=PROJECT_DIR,
        settings_module=SETTINGS_MODULE,
    )
    assert (bare.project_dir, bare.settings_module, bare.container) == (
        None,
        None,
        None,
    )


@pytest.mark.django_db
def test_a_compose_application_runs_in_its_service_with_its_files_and_project(
    admin, compose_application
):
    profile = ServerConnectionService(admin).dbs_profile(compose_application)

    assert profile == DbsProfile(
        python="/opt/venv/bin/python",
        manage="/app/manage.py",
        project_dir="/srv/shop",
        settings_module="shop.settings",
        container=ContainerTarget(
            engine="podman",
            service="backend",
            files=("compose.yaml", "compose.prod.yaml"),
            project="shop",
            workdir="/app",
        ),
    )


@pytest.mark.django_db
def test_a_container_application_runs_in_its_named_container(
    admin, container_application
):
    target = container_of(container_application)

    assert target == ContainerTarget(
        engine="docker", container="blog-web-1", workdir="/code"
    )
    assert target.in_compose is False
    assert target.name == "blog-web-1"


@pytest.mark.django_db
def test_an_application_on_the_host_has_no_container(configured_application):
    assert container_of(configured_application) is None


@pytest.mark.django_db
def test_a_container_application_left_without_an_engine_runs_with_docker(
    admin, container_application
):
    ApplicationRepository().update(container_application, engine="")

    assert container_of(container_application).engine == "docker"


@pytest.mark.django_db
def test_a_host_application_stages_in_its_backup_folder_and_a_container_one_at_home(
    admin, configured_application, container_application
):
    connections = ServerConnectionService(admin)
    remote = healthy_remote()

    assert connections.staging_folder(configured_application, remote) == BACKUP_DIR
    assert connections.staging_folder(container_application, remote) == (
        f"{HOME}/.dbs-staging"
    )


@pytest.mark.django_db
def test_commands_are_bounded_inside_only_a_container_that_has_timeout(
    admin, configured_server, configured_application, container_application
):
    connections = ServerConnectionService(admin)
    ApplicationRepository().update(configured_application, timeout_in_container=True)
    ApplicationRepository().update(container_application, timeout_in_container=True)
    server = ServerService(admin).get(configured_server.pk)

    on_host = connections.credentials(server, application=configured_application)
    inside = connections.credentials(server, application=container_application)
    alone = connections.credentials(server)

    assert on_host.timeout_in_container is False
    assert inside.timeout_in_container is True
    assert alone.timeout_in_container is False
