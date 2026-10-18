from __future__ import annotations

import pytest

from dbs.manager.applications.services import ApplicationService
from dbs.manager.servers.repositories import ServerRepository
from tests.manager.factories import make_application
from tests.manager.servers.support import PASSWORD
from tests.manager.support import logged


def detail(server) -> str:
    return f"/api/servers/{server.pk}/"


def alive(server) -> bool:
    return ServerRepository().active().filter(pk=server.pk).exists()


@pytest.mark.django_db
def test_deleting_a_server_needs_the_password(api, admin, configured_server):
    asked = api.delete(detail(configured_server))
    wrong = api.delete(
        detail(configured_server), {"account_password": "wrong"}, format="json"
    )
    kept = alive(configured_server)
    deleted = api.delete(
        detail(configured_server), {"account_password": PASSWORD}, format="json"
    )

    assert asked.json()["error"]["fields"] == {"account_password": ["required"]}
    assert wrong.json()["error"]["code"] == "invalid_password"
    assert kept
    assert deleted.status_code == 204
    assert not alive(configured_server)
    assert [
        (entry.status, entry.error_code, entry.actor)
        for entry in logged("server.delete")
    ] == [("succeeded", "", admin), ("failed", "invalid_password", admin)]


@pytest.mark.django_db
def test_a_server_that_runs_an_application_is_not_deleted(
    api, admin, configured_server
):
    application = make_application(admin, name="shop", server=configured_server)

    refused = api.delete(
        detail(configured_server), {"account_password": PASSWORD}, format="json"
    )

    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "server_has_applications"
    assert alive(configured_server)
    assert ApplicationService(admin).get(application.pk).server == configured_server
    assert logged("server.delete") == []


@pytest.mark.django_db
def test_a_server_whose_applications_were_removed_can_be_deleted(
    api, admin, configured_server
):
    application = make_application(admin, name="shop", server=configured_server)
    ApplicationService(admin).delete(application.pk, account_password=PASSWORD)

    deleted = api.delete(
        detail(configured_server), {"account_password": PASSWORD}, format="json"
    )

    assert deleted.status_code == 204
    assert not alive(configured_server)
