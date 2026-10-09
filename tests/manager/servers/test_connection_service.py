from __future__ import annotations

from uuid import uuid4

import pytest
from rest_framework.exceptions import NotFound

from dbs.manager.servers.gateways import DbsProfile
from dbs.manager.servers.services import ServerConnectionService, ServerService
from tests.manager.servers.support import (
    PASSWORD,
    PROJECT_DIR,
    PYTHON,
    SETTINGS_MODULE,
    connecting_to,
    healthy_remote,
)

CONNECT = "dbs.manager.servers.services.connection_service.connect"


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
def test_an_unknown_or_deleted_server_does_not_open(
    admin, monkeypatch, configured_server
):
    monkeypatch.setattr(CONNECT, connecting_to(healthy_remote()))
    ServerService(admin).delete(configured_server.pk)
    connections = ServerConnectionService(admin)

    for server_id in (configured_server.pk, uuid4()):
        with pytest.raises(NotFound), connections.open(server_id):
            pass


@pytest.mark.django_db
def test_a_dbs_profile_says_where_and_how_manage_py_runs(admin, configured_server):
    connections = ServerConnectionService(admin)

    configured = connections.dbs_profile(configured_server)
    bare = connections.dbs_profile(
        ServerService(admin).update(
            configured_server.pk,
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
    assert (bare.project_dir, bare.settings_module) == (None, None)
