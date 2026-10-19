from __future__ import annotations

import pytest

from dbs.manager.applications.repositories import ApplicationRepository
from dbs.manager.servers.repositories import ServerRepository
from tests.manager.factories import make_application, make_server
from tests.manager.servers.support import PASSWORD, host_key_line
from tests.manager.support import logged


def merge(server) -> str:
    return f"/api/servers/{server.pk}/merge/"


def joining(api, source, target, account_password=PASSWORD):
    return api.post(
        merge(source),
        {"into": str(target.pk), "account_password": account_password},
        format="json",
    )


def applications_on(server) -> list[str]:
    return [
        application.name for application in ApplicationRepository().on_server(server.pk)
    ]


@pytest.fixture
def twin(admin, configured_server):
    return make_server(
        admin,
        name="web-1-again",
        host=configured_server.host,
        port=configured_server.port,
        username=configured_server.username,
        host_key=configured_server.host_key,
    )


@pytest.mark.django_db
def test_two_servers_that_are_one_machine_are_joined(
    api, admin, configured_server, twin
):
    make_application(admin, name="shop", server=configured_server)
    make_application(admin, name="blog", server=twin)
    make_application(admin, name="wiki", server=twin)

    response = joining(api, twin, configured_server)

    assert response.status_code == 200
    assert response.json()["id"] == str(configured_server.pk)
    assert applications_on(configured_server) == ["blog", "shop", "wiki"]
    assert not ServerRepository().active().filter(pk=twin.pk).exists()
    kept = ServerRepository().all_including_deleted().get(pk=twin.pk)
    assert kept.deleted_at is not None
    [entry] = logged("server.merge")
    assert (entry.status, entry.subject, entry.target_name) == (
        "succeeded",
        str(configured_server.pk),
        configured_server.name,
    )
    assert entry.data == {"merged": twin.name, "applications": 2}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "difference",
    [
        {"host": "10.0.0.9"},
        {"port": 22},
        {"username": "root"},
        {"host_key": host_key_line()},
    ],
)
def test_servers_that_differ_are_never_joined(
    api, admin, configured_server, difference
):
    reach = {
        "host": configured_server.host,
        "port": configured_server.port,
        "username": configured_server.username,
        "host_key": configured_server.host_key,
        **difference,
    }
    other = make_server(admin, name="other", **reach)
    make_application(admin, name="blog", server=other)

    response = joining(api, other, configured_server)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "servers_differ"
    assert applications_on(other) == ["blog"]
    assert ServerRepository().active().filter(pk=other.pk).exists()
    assert logged("server.merge") == []


@pytest.mark.django_db
def test_a_server_is_not_joined_with_itself(api, configured_server):
    response = joining(api, configured_server, configured_server)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "servers_differ"
    assert ServerRepository().active().filter(pk=configured_server.pk).exists()


@pytest.mark.django_db
def test_joining_needs_the_users_password(api, admin, configured_server, twin):
    make_application(admin, name="blog", server=twin)

    missing = joining(api, twin, configured_server, account_password="")
    wrong = joining(api, twin, configured_server, account_password="wrong")

    assert missing.json()["error"]["fields"] == {"account_password": ["required"]}
    assert wrong.json()["error"]["code"] == "invalid_password"
    assert applications_on(twin) == ["blog"]
    assert ServerRepository().active().filter(pk=twin.pk).exists()
    [entry] = logged("server.merge")
    assert (entry.status, entry.error_code) == ("failed", "invalid_password")


@pytest.mark.django_db
def test_joining_into_an_unknown_server_is_not_found(api, configured_server):
    response = api.post(
        merge(configured_server),
        {
            "into": "00000000-0000-0000-0000-000000000000",
            "account_password": PASSWORD,
        },
        format="json",
    )

    assert response.status_code == 404
