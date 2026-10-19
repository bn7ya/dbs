from __future__ import annotations

import base64
import hashlib
import re

import pytest

from dbs.manager.servers.gateways import parse_host_key
from dbs.manager.servers.models import Server
from dbs.manager.servers.repositories import ServerRepository
from dbs.manager.servers.services import ServerConnectionService
from tests.manager.factories import make_server
from tests.manager.servers.support import host_key_line
from tests.manager.support import logged

SERVERS = "/api/servers/"
FETCH_HOST_KEY = "dbs.manager.servers.services.server_service.fetch_host_key"
FINGERPRINT = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")


@pytest.mark.django_db
def test_a_fingerprint_reads_as_openssh_prints_it(api, monkeypatch):
    line = host_key_line()
    monkeypatch.setattr(FETCH_HOST_KEY, lambda host, port: parse_host_key(line))

    body = api.post(f"{SERVERS}fingerprint/", {"host": "10.0.0.9", "port": 22}).json()

    blob = base64.b64decode(line.split()[1])
    expected = "SHA256:" + base64.b64encode(
        hashlib.sha256(blob).digest()
    ).decode().rstrip("=")
    assert body["fingerprint"] == expected
    assert FINGERPRINT.match(body["fingerprint"])


@pytest.mark.django_db
def test_a_server_added_with_a_generated_key_shows_its_public_half(api, admin):
    response = api.post(
        SERVERS,
        {
            "name": "web-1",
            "host": "10.0.0.5",
            "username": "deploy",
            "host_key": host_key_line(),
            "generate_key": True,
        },
        format="json",
    )

    assert response.status_code == 201
    body = response.json()
    public_key = body["public_key"]
    assert public_key.startswith("ssh-ed25519 ") and public_key.endswith(" django-dbs")
    assert body["authorized_keys_hint"] == (
        f"echo '{public_key}' >> ~deploy/.ssh/authorized_keys"
    )
    assert (body["auth_method"], body["has_private_key"]) == ("key", True)
    assert "private_key" not in body
    server = ServerRepository().get(body["id"])
    assert (
        "OPENSSH PRIVATE KEY"
        in ServerConnectionService(admin).credentials(server).private_key
    )
    [entry] = logged("server.keypair")
    assert entry.subject == body["id"]
    assert FINGERPRINT.match(entry.data["fingerprint"])
    assert api.get(f"{SERVERS}{body['id']}/public-key/").json() == {
        "public_key": public_key
    }


@pytest.mark.django_db
def test_a_server_without_a_key_choice_is_refused(api):
    response = api.post(
        SERVERS,
        {
            "name": "web-1",
            "host": "10.0.0.5",
            "username": "deploy",
            "host_key": host_key_line(),
        },
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["fields"]["auth_method"] == ["required"]


@pytest.mark.django_db
def test_the_public_key_is_derived_from_a_pasted_private_key(api, admin):
    server = make_server(admin)

    public_key = api.get(f"{SERVERS}{server.pk}/public-key/").json()["public_key"]

    assert public_key.startswith("ssh-ed25519 AAAA")


@pytest.mark.django_db
def test_a_password_server_has_no_public_key(api, admin):
    server = make_server(
        admin,
        auth_method=Server.AuthMethod.PASSWORD,
        private_key="",
        password="secret-1",
    )

    response = api.get(f"{SERVERS}{server.pk}/public-key/")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_private_key"
