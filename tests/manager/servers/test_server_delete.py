from __future__ import annotations

import pytest

from dbs.manager.servers.repositories import ServerRepository
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
