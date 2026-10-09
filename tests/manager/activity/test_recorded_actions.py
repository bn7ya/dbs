from __future__ import annotations

import pytest

from dbs import audit
from dbs.manager.servers.exceptions import HostKeyChanged, SSHUnreachable
from dbs.manager.servers.gateways import parse_host_key
from tests.manager.servers.support import (
    BACKUP_PASSPHRASE,
    KEY_PASSPHRASE,
    PASSWORD,
    SSH_PASSWORD,
    body_line,
    connecting_to,
    healthy_remote,
    host_key_line,
    refusing_with,
)

CONNECT = "dbs.manager.servers.services.connection_service.connect"
FETCH_HOST_KEY = "dbs.manager.servers.services.server_service.fetch_host_key"
LOG = "/api/activity/"


def server_url(server_id, action: str = "") -> str:
    return f"/api/servers/{server_id}/{action}"


def latest(logged, action: str):
    return logged(action)[0]


@pytest.mark.django_db
def test_adding_a_server_is_logged(api, admin, logged, private_key):
    response = api.post(
        "/api/servers/",
        {
            "name": "web-2",
            "host": "10.0.0.6",
            "username": "deploy",
            "auth_method": "key",
            "private_key": private_key,
            "host_key": host_key_line(),
        },
    )

    entry = latest(logged, "server.create")
    assert entry.subject == response.json()["id"]
    assert entry.target_name == "web-2"
    assert entry.actor == admin
    assert entry.status == audit.SUCCEEDED
    assert entry.remote_addr == "127.0.0.1"


@pytest.mark.django_db
def test_a_refused_server_is_not_logged(api, logged):
    api.post("/api/servers/", {"name": "web-2", "host": "10.0.0.6"})

    assert logged("server.create") == []


@pytest.mark.django_db
def test_a_change_names_the_fields_it_changed(api, logged, server):
    api.patch(
        server_url(server.pk),
        {
            "name": "web-1",
            "port": 2222,
            "username": "deploy",
            "project_dir": "/srv/app",
            "account_password": PASSWORD,
        },
    )

    entry = latest(logged, "server.update")
    assert entry.target_name == "web-1"
    assert entry.subject == str(server.pk)
    assert entry.data == {"fields": ["port", "project_dir"]}


@pytest.mark.django_db
def test_a_changed_secret_is_named_and_never_valued(api, logged, server):
    api.patch(
        server_url(server.pk),
        {
            "auth_method": "password",
            "password": SSH_PASSWORD,
            "backup_passphrase": "new-one",
            "account_password": PASSWORD,
        },
    )

    entry = latest(logged, "server.update")
    assert entry.data == {
        "fields": [
            "auth_method",
            "backup_passphrase",
            "key_passphrase",
            "password",
            "private_key",
        ]
    }


@pytest.mark.django_db
def test_an_empty_secret_is_not_a_change(api, logged, server):
    api.patch(server_url(server.pk), {"private_key": "", "key_passphrase": ""})

    assert latest(logged, "server.update").data == {"fields": []}


@pytest.mark.django_db
def test_deleting_a_server_is_logged(api, logged, server):
    api.delete(server_url(server.pk))

    entry = latest(logged, "server.delete")
    assert entry.subject == str(server.pk)
    assert entry.target_name == "web-1"


@pytest.mark.django_db
def test_reading_a_fingerprint_is_logged_against_the_address(api, logged, monkeypatch):
    presented = parse_host_key(host_key_line())
    monkeypatch.setattr(FETCH_HOST_KEY, lambda host, port: presented)

    api.post("/api/servers/fingerprint/", {"host": "10.0.0.9", "port": 2222})

    entry = latest(logged, "server.fingerprint")
    assert entry.subject == ""
    assert entry.target_name == "10.0.0.9:2222"
    assert entry.data == {"fingerprint": presented.fingerprint}
    assert entry.status == audit.SUCCEEDED


@pytest.mark.django_db
def test_an_ipv6_address_keeps_its_port_readable(api, logged, monkeypatch):
    def unreachable(host, port):
        raise SSHUnreachable()

    monkeypatch.setattr(FETCH_HOST_KEY, unreachable)

    api.post("/api/servers/fingerprint/", {"host": "2001:db8::5"})

    entry = latest(logged, "server.fingerprint")
    assert entry.target_name == "[2001:db8::5]:22"
    assert entry.status == audit.FAILED
    assert entry.error_code == "ssh_unreachable"


@pytest.mark.django_db
def test_a_check_is_logged_with_its_result(api, logged, monkeypatch, server):
    monkeypatch.setattr(CONNECT, connecting_to(healthy_remote()))

    api.post(server_url(server.pk, "check/"))

    entry = latest(logged, "server.check")
    assert entry.subject == str(server.pk)
    assert entry.status == audit.SUCCEEDED
    assert entry.data == {"status": "problem"}
    assert entry.finished_at >= entry.started_at


@pytest.mark.django_db
def test_a_check_that_cannot_connect_is_logged_failed(api, logged, monkeypatch, server):
    monkeypatch.setattr(CONNECT, refusing_with(HostKeyChanged()))

    assert api.post(server_url(server.pk, "check/")).status_code == 409

    entry = latest(logged, "server.check")
    assert entry.status == audit.FAILED
    assert entry.error_code == "host_key_changed"
    assert entry.data == {"status": "failed"}
    assert entry.finished_at is not None


@pytest.mark.django_db
def test_trusting_a_new_host_key_is_logged_with_its_fingerprint(api, logged, server):
    replacement = host_key_line()

    api.post(
        server_url(server.pk, "host-key/"),
        {"host_key": replacement, "password": PASSWORD},
    )

    entry = latest(logged, "server.repin")
    assert entry.status == audit.SUCCEEDED
    assert entry.subject == str(server.pk)
    assert entry.data == {"fingerprint": parse_host_key(replacement).fingerprint}


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("action", "path", "payload"),
    [
        (
            "server.repin",
            "host-key/",
            {"host_key": "ssh-ed25519 AAAA", "password": "wrong"},
        ),
        ("server.passphrase_reveal", "passphrase/", {"password": "wrong"}),
    ],
)
def test_a_refused_password_is_logged_failed(
    api, logged, server, action, path, payload
):
    assert api.post(server_url(server.pk, path), payload).status_code == 400

    entry = latest(logged, action)
    assert entry.status == audit.FAILED
    assert entry.error_code == "invalid_password"
    assert entry.subject == str(server.pk)
    assert entry.data == {}


@pytest.mark.django_db
def test_a_refused_host_key_is_logged_with_its_own_code(api, logged, server):
    response = api.post(
        server_url(server.pk, "host-key/"),
        {"host_key": "not a key", "password": PASSWORD},
    )

    assert response.json()["error"]["code"] == "invalid"
    entry = latest(logged, "server.repin")
    assert entry.status == audit.FAILED
    assert entry.error_code == "invalid_host_key"


@pytest.mark.django_db
def test_showing_the_passphrase_is_logged(api, logged, server):
    api.post(server_url(server.pk, "passphrase/"), {"password": PASSWORD})

    entry = latest(logged, "server.passphrase_reveal")
    assert entry.status == audit.SUCCEEDED
    assert entry.target_name == "web-1"
    assert entry.data == {}


@pytest.mark.django_db
def test_no_secret_reaches_the_log(api, monkeypatch, server, private_key):
    replacement_key = host_key_line()
    monkeypatch.setattr(CONNECT, refusing_with(SSHUnreachable()))
    api.patch(
        server_url(server.pk),
        {
            "private_key": private_key,
            "key_passphrase": KEY_PASSPHRASE,
            "account_password": PASSWORD,
        },
    )
    api.patch(
        server_url(server.pk),
        {"backup_passphrase": BACKUP_PASSPHRASE, "account_password": PASSWORD},
    )
    api.patch(
        server_url(server.pk),
        {
            "auth_method": "password",
            "password": SSH_PASSWORD,
            "account_password": PASSWORD,
        },
    )
    api.patch(
        server_url(server.pk),
        {"project_dir": "/srv/other", "account_password": f"{PASSWORD}-typo"},
    )
    api.post(server_url(server.pk, "check/"))
    api.post(server_url(server.pk, "passphrase/"), {"password": PASSWORD})
    api.post(server_url(server.pk, "passphrase/"), {"password": f"{PASSWORD}-typo"})
    api.post(
        server_url(server.pk, "host-key/"),
        {"host_key": replacement_key, "password": PASSWORD},
    )
    api.post("/api/auth/logout/")
    api.post("/api/auth/login/", {"username": "sara", "password": f"{PASSWORD}-typo"})
    api.post("/api/auth/login/", {"username": "sara", "password": PASSWORD})

    response = api.get(LOG, {"page_size": 200})

    assert response.json()["count"] == 12
    body = response.content.decode()
    for secret in (
        body_line(private_key),
        KEY_PASSPHRASE,
        SSH_PASSWORD,
        BACKUP_PASSPHRASE,
        PASSWORD,
    ):
        assert secret not in body
    assert "sealed" not in body


@pytest.mark.django_db
def test_signing_in_is_logged(anonymous, admin, logged):
    anonymous.post("/api/auth/login/", {"username": "sara", "password": PASSWORD})

    entry = latest(logged, "auth.sign_in")
    assert entry.actor == admin
    assert entry.target_name == "sara"
    assert entry.status == audit.SUCCEEDED
    assert entry.remote_addr == "127.0.0.1"


@pytest.mark.django_db
@pytest.mark.parametrize("username", ["sara", "Nobody-Here"])
def test_a_refused_sign_in_is_logged_with_no_actor(anonymous, admin, logged, username):
    anonymous.post("/api/auth/login/", {"username": username, "password": "wrong"})

    entry = latest(logged, "auth.sign_in_failed")
    assert entry.actor is None
    assert entry.target_name == username
    assert entry.status == audit.FAILED
    assert entry.error_code == "authentication_failed"
    assert logged("auth.sign_in") == []


@pytest.mark.django_db
def test_signing_out_is_logged(api, admin, logged):
    api.post("/api/auth/logout/")

    entry = latest(logged, "auth.sign_out")
    assert entry.actor == admin
    assert entry.target_name == "sara"
