from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from dbs.manager.servers.exceptions import (
    HostKeyConfirmationMismatch,
    HostKeyConfirmationMissing,
    HostKeyNotConfirmed,
    HostKeyRejected,
)
from dbs.manager.servers.gateways import parse_host_key
from dbs.manager.servers.models import Server
from dbs.manager.servers.services import HostKeyConfirmationService
from tests.manager.servers.support import SSH_PASSWORD, host_key_line

FETCH_HOST_KEY = "dbs.manager.servers.services.server_service.fetch_host_key"
SERVICE_CLOCK = "dbs.manager.servers.services.host_key_confirmation_service.timezone"


class Later:
    def now(self):
        return timezone.now() + timedelta(minutes=11)


@pytest.fixture(autouse=True)
def offered(monkeypatch):
    key = parse_host_key(host_key_line())
    monkeypatch.setattr(FETCH_HOST_KEY, lambda host, port: key)
    return key


def adding(mcp, confirmation, host="10.0.0.5", port=22):
    return mcp(
        "add_server",
        name="web-1",
        host=host,
        port=port,
        username="deploy",
        confirmation=confirmation,
        auth_method="password",
        password=SSH_PASSWORD,
    )


@pytest.mark.django_db
def test_reading_a_host_key_hands_back_a_confirmation_for_a_person(mcp, offered):
    held = mcp("fingerprint_host", host="10.0.0.5")

    assert held.ok, held.text
    assert held.data["fingerprint"] == offered.fingerprint
    assert held.data["status"] == "pending"
    assert held.data["confirm_with"] == (
        f"django_dbs server confirm-host-key {held.data['id']}"
    )
    assert "line" not in held.data
    assert not Server.objects.exists()


@pytest.mark.django_db
def test_a_key_nobody_confirmed_is_not_pinned(mcp):
    held = mcp("fingerprint_host", host="10.0.0.5").data

    added = adding(mcp, held["id"])

    assert not added.ok and added.text == HostKeyNotConfirmed.default_detail
    assert not Server.objects.exists()


@pytest.mark.django_db
def test_a_rejected_key_is_not_pinned(mcp, admin):
    held = mcp("fingerprint_host", host="10.0.0.5").data
    HostKeyConfirmationService(admin).reject(held["id"])

    added = adding(mcp, held["id"])

    assert not added.ok and added.text == HostKeyRejected.default_detail
    assert not Server.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(("host", "port"), [("10.0.0.6", 22), ("10.0.0.5", 2222)])
def test_a_confirmation_for_another_address_is_refused(mcp, admin, host, port):
    held = mcp("fingerprint_host", host="10.0.0.5").data
    HostKeyConfirmationService(admin).confirm(held["id"])

    added = adding(mcp, held["id"], host=host, port=port)

    assert not added.ok
    assert added.text == HostKeyConfirmationMismatch.default_detail
    assert not Server.objects.exists()


@pytest.mark.django_db
def test_an_expired_or_made_up_confirmation_is_refused(mcp, admin, monkeypatch):
    held = mcp("fingerprint_host", host="10.0.0.5").data
    HostKeyConfirmationService(admin).confirm(held["id"])
    made_up = adding(mcp, "12345678")
    monkeypatch.setattr(SERVICE_CLOCK, Later())

    expired = adding(mcp, held["id"])

    missing = str(HostKeyConfirmationMissing.default_detail)
    assert not made_up.ok and made_up.text == missing
    assert not expired.ok and expired.text == missing
    assert not Server.objects.exists()


@pytest.mark.django_db
def test_a_confirmed_key_is_pinned_once(mcp, admin, offered):
    held = mcp("fingerprint_host", host="10.0.0.5").data
    HostKeyConfirmationService(admin).confirm(held["id"])

    added = adding(mcp, held["id"])
    again = mcp(
        "add_server",
        name="web-2",
        host="10.0.0.5",
        username="deploy",
        confirmation=held["id"],
        auth_method="generate_key",
    )

    assert added.ok, added.text
    assert Server.objects.get().host_key == offered.line
    assert not again.ok
    assert again.text == str(HostKeyConfirmationMissing.default_detail)
