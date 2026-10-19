from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from dbs.manager.accounts.models import Account
from dbs.manager.accounts.repositories import UserRepository
from tests.manager.support import PASSWORD, logged

NEW_PASSWORD = "a-brand-new-long-passphrase"
PASSWORD_URL = "/api/auth/password/"


@pytest.fixture
def sara(db):
    return UserRepository().create(username="sara", password=PASSWORD)


@pytest.fixture
def client(sara):
    client = APIClient()
    client.force_login(sara)
    return client


def aged(user, days):
    Account.objects.filter(user=user).update(
        password_changed_at=timezone.now() - timedelta(days=days)
    )


def error(response):
    return response.json()["error"]


@pytest.mark.django_db
def test_a_password_younger_than_thirty_days_changes_nothing(client, sara):
    aged(sara, 29)

    assert client.get("/api/servers/").status_code == 200
    assert client.get("/api/auth/me/").json()["password_change_required"] is False


@pytest.mark.django_db
def test_an_expired_password_leaves_only_the_change_and_signing_out(client, sara):
    aged(sara, 30)

    refused = client.get("/api/servers/")
    me = client.get("/api/auth/me/")

    assert refused.status_code == 403
    assert error(refused)["code"] == "password_change_required"
    assert me.status_code == 200 and me.json()["password_change_required"] is True
    assert client.get("/api/dashboard/").status_code == 403
    assert client.post("/api/backups/take/", {"application": "x"}).status_code == 403
    assert client.get("/").status_code == 200
    assert client.post("/api/auth/logout/").status_code == 204


@pytest.mark.django_db
def test_changing_an_expired_password_lifts_the_restriction(client, sara):
    aged(sara, 45)

    changed = client.post(
        PASSWORD_URL, {"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    )

    assert changed.status_code == 200
    assert changed.json()["password_change_required"] is False
    assert client.get("/api/servers/").status_code == 200
    sara.refresh_from_db()
    assert sara.check_password(NEW_PASSWORD)
    assert Account.objects.get(user=sara).password_changed_at > timezone.now() - (
        timedelta(minutes=1)
    )
    assert logged("account.password")[0].actor == sara


@pytest.mark.django_db
def test_the_new_password_must_differ_and_pass_the_validators(client, sara):
    aged(sara, 31)

    same = client.post(
        PASSWORD_URL, {"current_password": PASSWORD, "new_password": PASSWORD}
    )
    short = client.post(
        PASSWORD_URL, {"current_password": PASSWORD, "new_password": "abc"}
    )
    wrong = client.post(
        PASSWORD_URL, {"current_password": "nope", "new_password": NEW_PASSWORD}
    )

    assert error(same)["fields"] == {"new_password": ["password_unchanged"]}
    assert "password_too_short" in error(short)["fields"]["new_password"]
    assert error(wrong)["code"] == "invalid_password"
    assert client.get("/api/servers/").status_code == 403


@pytest.mark.django_db
def test_the_password_change_keeps_this_session_signed_in(client):
    client.post(
        PASSWORD_URL, {"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    )

    assert client.get("/api/auth/me/").status_code == 200


@pytest.mark.django_db
def test_the_identity_says_when_the_password_expires(client, sara):
    aged(sara, 10)

    identity = client.get("/api/auth/me/").json()

    assert identity["password_expires_at"] > identity["password_changed_at"]
