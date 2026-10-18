from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.applications.services import ApplicationService
from dbs.manager.servers.repositories import ServerRepository
from dbs.manager.servers.services import ServerConnectionService
from tests.manager.factories import make_application, make_server
from tests.manager.servers.support import (
    BACKUP_PASSPHRASE,
    KEY_PASSPHRASE,
    PASSWORD,
    SSH_PASSWORD,
    body_line,
    host_key_line,
    private_key_text,
)
from tests.manager.support import needs_partial_unique_constraints

LIST = "/api/servers/"
SERVER_FIELDS = {
    "id",
    "name",
    "host",
    "port",
    "username",
    "auth_method",
    "has_private_key",
    "has_key_passphrase",
    "has_password",
    "host_key",
    "host_key_type",
    "host_key_fingerprint",
    "engines",
    "last_check_status",
    "last_check_error",
    "last_checked_at",
    "last_check_report",
    "timeout_on_host",
    "connection_state",
    "last_seen_at",
    "last_connection_error",
    "created_at",
    "updated_at",
}


def detail(server_id) -> str:
    return f"/api/servers/{server_id}/"


def new_server(host_key: str, private_key: str, **overrides) -> dict:
    return {
        "name": "web-1",
        "host": "web-1.example.com",
        "username": "deploy",
        "auth_method": "key",
        "private_key": private_key,
        "key_passphrase": KEY_PASSPHRASE,
        "host_key": host_key,
        **overrides,
    }


def assert_no_secrets(response, private_key: str) -> None:
    body = response.content.decode()
    for secret in (body_line(private_key), KEY_PASSPHRASE, SSH_PASSWORD):
        assert secret not in body
    assert "sealed" not in body


@pytest.mark.django_db
def test_adding_a_server_pins_the_host_key_and_returns_it_without_secrets(
    api, host_key, private_key
):
    response = api.post(LIST, new_server(host_key, private_key))

    assert response.status_code == 201
    body = response.json()
    assert set(body) == SERVER_FIELDS
    assert body["host_key"] == host_key
    assert body["host_key_type"] == "ssh-ed25519"
    assert body["host_key_fingerprint"].startswith("SHA256:")
    assert body["has_private_key"] is True
    assert body["has_key_passphrase"] is True
    assert body["has_password"] is False
    assert body["last_check_status"] == "unknown"
    assert body["last_check_report"] == {}
    assert_no_secrets(response, private_key)


@pytest.mark.django_db
def test_a_server_left_to_its_defaults_answers_on_port_22_and_knows_no_engine_yet(
    api, host_key, private_key
):
    body = api.post(LIST, new_server(host_key, private_key)).json()

    assert body["port"] == 22
    assert body["engines"] == {}
    assert body["timeout_on_host"] is None
    assert body["connection_state"] == "unknown"


@pytest.mark.django_db
def test_a_server_holds_only_how_to_reach_it_and_ignores_project_settings(
    api, host_key, private_key
):
    response = api.post(
        LIST,
        new_server(
            host_key,
            private_key,
            project_dir="/srv/app",
            python_path="/srv/app/.venv/bin/python",
            remote_backup_dir="/var/backups/dbs",
            file_roots=["/srv/app/media"],
            env_path="/srv/app/.env",
            backup_passphrase=BACKUP_PASSPHRASE,
        ),
        format="json",
    )

    assert response.status_code == 201
    assert set(response.json()) == SERVER_FIELDS
    assert BACKUP_PASSPHRASE not in response.content.decode()
    server = ServerRepository().get(response.json()["id"])
    assert not hasattr(server, "project_dir")
    assert ApplicationService(None).list().count() == 0


@pytest.mark.django_db
def test_adding_a_server_requires_a_host_key(api, private_key):
    payload = new_server("", private_key)
    del payload["host_key"]

    response = api.post(LIST, payload)

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"host_key": ["required"]}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "line",
    [
        "not a key",
        "ssh-ed25519 !!!!",
        "foo AAAAA2Zvbw==",
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAAmFi",
    ],
)
def test_a_host_key_that_is_not_one_is_refused_with_its_code(api, private_key, line):
    response = api.post(LIST, new_server(line, private_key))

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"host_key": ["invalid_host_key"]}


@pytest.mark.django_db
def test_a_host_key_line_is_stored_without_its_comment(api, host_key, private_key):
    response = api.post(LIST, new_server(f"{host_key} root@web-1", private_key))

    assert response.json()["host_key"] == host_key


@pytest.mark.django_db
def test_the_key_method_needs_a_private_key(api, host_key):
    response = api.post(LIST, new_server(host_key, ""))

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {
        "private_key": ["private_key_required"]
    }


@pytest.mark.django_db
def test_the_password_method_needs_a_password(api, host_key, private_key):
    response = api.post(LIST, new_server(host_key, private_key, auth_method="password"))

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"password": ["password_required"]}


@pytest.mark.django_db
def test_the_password_method_stores_only_the_password(api, host_key, private_key):
    response = api.post(
        LIST,
        new_server(
            host_key, private_key, auth_method="password", password=SSH_PASSWORD
        ),
    )

    body = response.json()
    assert body["has_password"] is True
    assert body["has_private_key"] is False
    assert body["has_key_passphrase"] is False
    assert_no_secrets(response, private_key)


@pytest.mark.django_db
def test_a_name_in_use_is_refused(api, configured_server, host_key, private_key):
    response = api.post(
        LIST, new_server(host_key, private_key, name=configured_server.name)
    )

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"name": ["name_taken"]}


@pytest.mark.django_db
def test_a_deleted_servers_name_is_free_again(
    api, configured_server, host_key, private_key
):
    api.delete(
        detail(configured_server.pk), {"account_password": PASSWORD}, format="json"
    )

    response = api.post(
        LIST, new_server(host_key, private_key, name=configured_server.name)
    )

    assert response.status_code == 201


@pytest.mark.django_db
def test_a_host_that_could_be_an_option_is_refused(api, host_key, private_key):
    response = api.post(
        LIST, new_server(host_key, private_key, host="-oProxyCommand=id")
    )

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"host": ["invalid"]}


@pytest.mark.django_db
def test_the_list_is_paginated_searchable_and_free_of_secrets(
    api, configured_server, private_key
):
    api.post(
        LIST,
        new_server(host_key_line(), private_key, name="db-1", host="db-1.example.com"),
    )

    everything = api.get(LIST)
    searched = api.get(LIST, {"search": "WEB"})
    by_host = api.get(LIST, {"search": "example.com"})

    assert everything.status_code == 200
    body = everything.json()
    assert set(body) == {"count", "next", "previous", "results"}
    assert [row["name"] for row in body["results"]] == ["db-1", "web-1"]
    assert set(body["results"][0]) == {
        "id",
        "name",
        "host",
        "port",
        "username",
        "engines",
        "application_count",
        "last_check_status",
        "last_checked_at",
        "connection_state",
        "last_seen_at",
        "last_connection_error",
    }
    assert [row["name"] for row in searched.json()["results"]] == ["web-1"]
    assert [row["name"] for row in by_host.json()["results"]] == ["db-1"]
    assert_no_secrets(everything, private_key)


@pytest.mark.django_db
def test_the_list_counts_the_applications_each_server_still_runs(
    api, admin, configured_server
):
    make_application(admin, name="shop", server=configured_server)
    removed = make_application(admin, name="blog", server=configured_server)
    ApplicationService(admin).delete(removed.pk, account_password=PASSWORD)
    make_server(admin, name="db-1", host="10.0.0.6")

    rows = api.get(LIST).json()["results"]

    assert [(row["name"], row["application_count"]) for row in rows] == [
        ("db-1", 0),
        ("web-1", 1),
    ]


@pytest.mark.django_db
def test_the_detail_carries_no_secrets(api, configured_server, private_key):
    response = api.get(detail(configured_server.pk))

    assert response.status_code == 200
    assert response.json()["name"] == "web-1"
    assert set(response.json()) == SERVER_FIELDS
    assert_no_secrets(response, private_key)


@pytest.mark.django_db
def test_an_update_keeps_the_secrets_it_was_not_sent(
    api, admin, configured_server, private_key
):
    response = api.patch(
        detail(configured_server.pk),
        {"name": "web-2", "private_key": "", "key_passphrase": ""},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "web-2"
    assert body["has_private_key"] is True
    assert body["has_key_passphrase"] is True
    assert_no_secrets(response, private_key)
    stored = ServerRepository().get(configured_server.pk)
    credentials = ServerConnectionService(admin).credentials(stored)
    assert credentials.private_key == private_key
    assert credentials.key_passphrase == KEY_PASSPHRASE


@pytest.mark.django_db
def test_a_new_private_key_replaces_the_key_passphrase(api, admin, configured_server):
    replacement = private_key_text()

    response = api.patch(
        detail(configured_server.pk),
        {"private_key": replacement, "account_password": PASSWORD},
    )

    assert response.json()["has_key_passphrase"] is False
    credentials = ServerConnectionService(admin).credentials(
        ServerRepository().get(configured_server.pk)
    )
    assert credentials.private_key == replacement
    assert credentials.key_passphrase is None


@pytest.mark.django_db
def test_switching_to_a_password_needs_one_and_drops_the_key(
    api, admin, configured_server
):
    refused = api.patch(detail(configured_server.pk), {"auth_method": "password"})
    switched = api.patch(
        detail(configured_server.pk),
        {
            "auth_method": "password",
            "password": SSH_PASSWORD,
            "account_password": PASSWORD,
        },
    )

    assert refused.status_code == 400
    assert refused.json()["error"]["fields"] == {"password": ["password_required"]}
    body = switched.json()
    assert body["auth_method"] == "password"
    assert (
        body["has_password"],
        body["has_private_key"],
        body["has_key_passphrase"],
    ) == (
        True,
        False,
        False,
    )
    credentials = ServerConnectionService(admin).credentials(
        ServerRepository().get(configured_server.pk)
    )
    assert credentials.password == SSH_PASSWORD
    assert credentials.private_key is None


@pytest.mark.django_db
def test_switching_back_to_a_key_needs_one(api, configured_server):
    api.patch(
        detail(configured_server.pk),
        {
            "auth_method": "password",
            "password": SSH_PASSWORD,
            "account_password": PASSWORD,
        },
    )

    response = api.patch(detail(configured_server.pk), {"auth_method": "key"})

    assert response.json()["error"]["fields"] == {
        "private_key": ["private_key_required"]
    }


@pytest.mark.django_db
def test_an_update_cannot_change_the_host_key(api, configured_server, host_key):
    response = api.patch(detail(configured_server.pk), {"host_key": host_key_line()})

    assert response.status_code == 200
    assert response.json()["host_key"] == host_key


@pytest.mark.django_db
def test_an_update_checks_the_name(api, configured_server, host_key, private_key):
    api.post(LIST, new_server(host_key, private_key, name="db-1"))

    response = api.patch(detail(configured_server.pk), {"name": "db-1"})

    assert response.json()["error"]["fields"] == {"name": ["name_taken"]}


@pytest.mark.django_db
@needs_partial_unique_constraints
def test_a_name_taken_between_the_check_and_the_write_is_still_name_taken(
    api, monkeypatch, configured_server, host_key, private_key
):
    monkeypatch.setattr(
        ServerRepository, "name_in_use", lambda self, name, excluding=None: False
    )

    response = api.post(
        LIST, new_server(host_key, private_key, name=configured_server.name)
    )

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"name": ["name_taken"]}
    assert api.get(LIST).json()["count"] == 1


def server_as_sent(server) -> dict:
    return {
        "name": server.name,
        "host": server.host,
        "port": server.port,
        "username": server.username,
        "auth_method": server.auth_method,
    }


@pytest.mark.django_db
def test_a_rename_needs_no_password_even_sent_with_every_setting(
    api, configured_server
):
    response = api.patch(
        detail(configured_server.pk),
        server_as_sent(configured_server) | {"name": "web-2"},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "web-2"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "change",
    [
        {"host": "10.0.0.9"},
        {"port": 22},
        {"username": "root"},
        {"private_key": "-----BEGIN OPENSSH PRIVATE KEY-----"},
        {"key_passphrase": "another"},
        {"auth_method": "password", "password": "ssh-password"},
    ],
)
def test_changing_anything_but_the_name_needs_the_users_password(
    api, configured_server, change
):
    before = api.get(detail(configured_server.pk)).json()

    response = api.patch(detail(configured_server.pk), change, format="json")

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"account_password": ["required"]}
    assert api.get(detail(configured_server.pk)).json() == before
    assert list(ActivityRepository().filtered(action="server.update")) == []


@pytest.mark.django_db
def test_a_wrong_password_changes_nothing_and_is_logged(api, configured_server):
    before = api.get(detail(configured_server.pk)).json()

    response = api.patch(
        detail(configured_server.pk),
        {"host": "10.0.0.9", "account_password": f"{PASSWORD}-typo"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_password"
    assert api.get(detail(configured_server.pk)).json() == before
    [entry] = ActivityRepository().filtered(action="server.update")
    assert (entry.status, entry.error_code) == ("failed", "invalid_password")
    assert entry.data == {"fields": ["host"]}


@pytest.mark.django_db
def test_the_users_password_lets_the_change_through(api, configured_server):
    response = api.patch(
        detail(configured_server.pk),
        {"host": "10.0.0.9", "account_password": PASSWORD},
    )

    assert response.status_code == 200
    assert response.json()["host"] == "10.0.0.9"
    [entry] = ActivityRepository().filtered(action="server.update")
    assert (entry.status, entry.data) == ("succeeded", {"fields": ["host"]})


@pytest.mark.django_db
def test_wrong_passwords_for_changes_are_limited(api, settings, configured_server):
    settings.AUTH_FAILURES_PER_USER = 2
    change = {"host": "10.0.0.9"}
    for _ in range(2):
        api.patch(detail(configured_server.pk), change | {"account_password": "wrong"})

    refused = api.patch(
        detail(configured_server.pk), change | {"account_password": PASSWORD}
    )

    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "too_many_attempts"


@pytest.mark.django_db
def test_a_wrong_field_is_reported_before_the_password_is_asked_for(
    api, configured_server
):
    response = api.patch(
        detail(configured_server.pk),
        {"host": "-oProxyCommand=id", "account_password": "wrong"},
    )

    assert response.json()["error"]["fields"] == {"host": ["invalid"]}
    assert list(ActivityRepository().filtered(action="server.update")) == []


@pytest.mark.django_db
def test_a_server_added_in_the_last_hour_changes_without_the_password(
    api, admin, host_key, private_key
):
    server = api.post(LIST, new_server(host_key, private_key)).json()

    response = api.patch(detail(server["id"]), {"host": "10.0.0.9", "username": "root"})

    assert response.status_code == 200
    assert (response.json()["host"], response.json()["username"]) == (
        "10.0.0.9",
        "root",
    )


@pytest.mark.django_db
def test_after_an_hour_or_for_someone_else_a_change_needs_the_password(api, admin):
    older = make_server(admin, name="web-1", host="10.0.0.5")
    ServerRepository().update(older, created_at=timezone.now() - timedelta(hours=2))
    other = UserRepository().create(username="omar", password=PASSWORD)
    theirs = make_server(other, name="web-2", host="10.0.0.6")

    for server in (older, theirs):
        response = api.patch(detail(server.pk), {"host": "10.0.0.9"}, format="json")
        assert response.status_code == 400
        assert response.json()["error"]["fields"] == {"account_password": ["required"]}


@pytest.mark.django_db
def test_a_wrong_password_is_refused_even_where_none_is_needed(
    api, host_key, private_key
):
    server = api.post(LIST, new_server(host_key, private_key)).json()

    response = api.patch(
        detail(server["id"]),
        {"host": "10.0.0.9", "account_password": "not-the-password"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_password"
    assert ServerRepository().get(server["id"]).host == "web-1.example.com"


@pytest.mark.django_db
def test_deleting_hides_the_server_and_keeps_the_row(api, configured_server):
    response = api.delete(
        detail(configured_server.pk), {"account_password": PASSWORD}, format="json"
    )

    assert response.status_code == 204
    assert api.get(LIST).json()["count"] == 0
    assert api.get(detail(configured_server.pk)).status_code == 404
    kept = ServerRepository().all_including_deleted().get(pk=configured_server.pk)
    assert kept.deleted_at is not None


@pytest.mark.django_db
def test_an_unknown_server_is_not_found(api):
    response = api.get(detail("00000000-0000-0000-0000-000000000000"))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["discover/", "passphrase/", "passphrase/capture/"])
def test_a_server_offers_no_discovery_or_passphrase_of_its_own(
    api, configured_server, path
):
    response = api.post(detail(configured_server.pk) + path, {}, format="json")

    assert response.status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", ""),
        ("post", ""),
        ("post", "fingerprint/"),
        ("get", "{id}/"),
        ("patch", "{id}/"),
        ("delete", "{id}/"),
        ("post", "{id}/check/"),
        ("post", "{id}/host-key/"),
        ("get", "{id}/public-key/"),
        ("get", "{id}/browse/"),
        ("post", "{id}/merge/"),
    ],
)
def test_every_endpoint_needs_a_session(anonymous, configured_server, method, path):
    url = LIST + path.format(id=configured_server.pk)

    response = getattr(anonymous, method)(url, {})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_authenticated"
