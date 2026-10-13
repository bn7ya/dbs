from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.permissions import Role
from dbs.manager.servers.exceptions import (
    HostKeyConfirmationMismatch,
    HostKeyConfirmationMissing,
    HostKeyNotConfirmed,
    HostKeyRejected,
)
from dbs.manager.servers.gateways import parse_host_key
from dbs.manager.servers.services import HostKeyConfirmationService
from tests.manager.servers.support import PASSWORD, host_key_line
from tests.manager.support import logged

FETCH_HOST_KEY = "dbs.manager.servers.services.server_service.fetch_host_key"
SERVICE_CLOCK = "dbs.manager.servers.services.host_key_confirmation_service.timezone"
LIST = "/api/servers/host-keys/"


@pytest.fixture(autouse=True)
def offered(monkeypatch):
    key = parse_host_key(host_key_line())
    monkeypatch.setattr(FETCH_HOST_KEY, lambda host, port: key)
    return key


@pytest.fixture
def confirmations(admin):
    return HostKeyConfirmationService(admin)


class Later:
    def __init__(self, by):
        self.by = by

    def now(self):
        return timezone.now() + self.by


@pytest.mark.django_db
def test_a_host_key_read_for_claude_waits_for_a_person(api, confirmations, offered):
    held = confirmations.request("10.0.0.5", 2222)

    listed = api.get(LIST).json()

    assert len(held.id) == 8
    assert listed["count"] == 1
    [row] = listed["results"]
    assert row == {
        "id": held.id,
        "host": "10.0.0.5",
        "port": 2222,
        "key_type": offered.key_type,
        "fingerprint": offered.fingerprint,
        "status": "pending",
        "requested_at": row["requested_at"],
        "expires_at": row["expires_at"],
    }
    assert held.expires_at - held.requested_at == timedelta(minutes=10)
    assert [entry.target_name for entry in logged("server.fingerprint")] == [
        "10.0.0.5:2222"
    ]


@pytest.mark.django_db
def test_a_person_confirms_it_once_and_it_leaves_the_list(
    api, admin, confirmations, offered
):
    held = confirmations.request("10.0.0.5", 22)

    confirmed = api.post(f"{LIST}{held.id}/confirm/")
    again = api.post(f"{LIST}{held.id}/reject/")

    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "host_key_decided"
    assert api.get(LIST).json()["count"] == 0
    assert confirmations.approved(held.id, "10.0.0.5", 22) == offered.line
    [entry] = logged("server.host_key_confirm")
    assert (entry.actor, entry.target_name, entry.status) == (
        admin,
        "10.0.0.5:22",
        "succeeded",
    )
    assert entry.data == {"fingerprint": offered.fingerprint}


@pytest.mark.django_db
def test_a_rejected_key_is_never_approved(api, confirmations):
    held = confirmations.request("10.0.0.5", 22)

    rejected = api.post(f"{LIST}{held.id}/reject/")

    assert rejected.json()["status"] == "rejected"
    assert api.get(LIST).json()["count"] == 0
    with pytest.raises(HostKeyRejected):
        confirmations.approved(held.id, "10.0.0.5", 22)
    assert [entry.status for entry in logged("server.host_key_reject")] == ["succeeded"]


@pytest.mark.django_db
def test_an_unconfirmed_or_mismatching_key_is_not_approved(confirmations):
    held = confirmations.request("10.0.0.5", 22)

    with pytest.raises(HostKeyNotConfirmed):
        confirmations.approved(held.id, "10.0.0.5", 22)
    confirmations.confirm(held.id)
    for host, port in (("10.0.0.6", 22), ("10.0.0.5", 2222)):
        with pytest.raises(HostKeyConfirmationMismatch):
            confirmations.approved(held.id, host, port)


@pytest.mark.django_db
def test_a_confirmation_lasts_ten_minutes(api, monkeypatch, confirmations):
    held = confirmations.request("10.0.0.5", 22)
    confirmations.confirm(held.id)

    monkeypatch.setattr(SERVICE_CLOCK, Later(timedelta(minutes=10, seconds=1)))

    with pytest.raises(HostKeyConfirmationMissing):
        confirmations.approved(held.id, "10.0.0.5", 22)
    assert api.get(LIST).json()["count"] == 0
    assert api.post(f"{LIST}{held.id}/confirm/").status_code == 404


@pytest.mark.django_db
def test_a_settled_confirmation_is_gone(confirmations):
    held = confirmations.request("10.0.0.5", 22)
    confirmations.confirm(held.id)

    confirmations.settle(held.id)

    with pytest.raises(HostKeyConfirmationMissing):
        confirmations.approved(held.id, "10.0.0.5", 22)


@pytest.mark.django_db
@pytest.mark.parametrize("unknown", ["0badc0de", "not-an-id", "0BADC0DE", "a" * 300])
def test_an_unknown_confirmation_is_not_found(api, confirmations, unknown):
    response = api.post(f"{LIST}{unknown}/confirm/")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "host_key_confirmation_missing"
    with pytest.raises(HostKeyConfirmationMissing):
        confirmations.get(unknown)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "path"),
    [("get", ""), ("post", "0badc0de/confirm/"), ("post", "0badc0de/reject/")],
)
def test_every_confirmation_endpoint_needs_a_session(anonymous, method, path):
    response = getattr(anonymous, method)(LIST + path)

    assert response.status_code == 403


def signed_in_as(role):
    client = APIClient()
    client.force_login(UserRepository().create(username=role, password=PASSWORD, role=role))
    return client


@pytest.mark.django_db
@pytest.mark.parametrize("role", [Role.VIEWER, Role.OPERATOR])
def test_only_an_account_that_may_add_servers_decides_a_host_key(confirmations, role):
    held = confirmations.request("10.0.0.5", 22)
    client = signed_in_as(role)

    confirmed = client.post(f"{LIST}{held.id}/confirm/")
    rejected = client.post(f"{LIST}{held.id}/reject/")
    listed = client.get(LIST).json()

    for refused in (confirmed, rejected):
        assert refused.status_code == 403
        assert refused.json()["error"]["code"] == "role_required"
        assert "admin role or higher" in refused.json()["error"]["message"]
    assert [row["status"] for row in listed["results"]] == ["pending"]
    assert logged("server.host_key_confirm") == logged("server.host_key_reject") == []
    with pytest.raises(HostKeyNotConfirmed):
        confirmations.approved(held.id, "10.0.0.5", 22)


@pytest.mark.django_db
def test_an_admin_decides_a_host_key(confirmations):
    held = confirmations.request("10.0.0.5", 22)

    confirmed = signed_in_as(Role.ADMIN).post(f"{LIST}{held.id}/confirm/")

    assert confirmed.status_code == 200
    assert confirmations.approved(held.id, "10.0.0.5", 22) == held.line
