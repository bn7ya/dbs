from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.middleware import forwarded_client, trusted_networks
from tests.manager.support import PASSWORD, logged

PROXY = "10.0.0.5"
CLIENT = "203.0.113.9"
STRANGER = "198.51.100.1"


@pytest.fixture
def behind_proxy(settings):
    settings.DBS_MANAGER_TRUSTED_PROXIES = trusted_networks("10.0.0.0/24")
    settings.SECURE_HSTS_SECONDS = 31536000


def through(address, proto="https", forwarded=CLIENT):
    return APIClient(
        REMOTE_ADDR=address,
        HTTP_X_FORWARDED_PROTO=proto,
        HTTP_X_FORWARDED_FOR=f"{forwarded}, {address}",
    )


@pytest.mark.parametrize(
    ("header", "client"),
    [
        ("203.0.113.9", "203.0.113.9"),
        ("203.0.113.9, 10.0.0.7", "203.0.113.9"),
        ("192.0.2.1, 203.0.113.9, 10.0.0.7", "203.0.113.9"),
        ("10.0.0.8, 10.0.0.7", None),
        ("not-an-address, 10.0.0.7", None),
        ("", None),
    ],
)
def test_the_client_is_the_last_hop_outside_the_proxies(header, client):
    assert forwarded_client(header, trusted_networks("10.0.0.0/24")) == client


@pytest.mark.django_db
def test_the_proxy_marks_https_and_the_cookies_follow(behind_proxy):
    response = through(PROXY).get("/api/auth/csrf/")

    cookie = response.cookies["csrftoken"]
    assert cookie["secure"] is True and cookie["httponly"] is True
    assert response["Strict-Transport-Security"].startswith("max-age=31536000")
    assert response.json()["csrf_token"]


@pytest.mark.django_db
def test_headers_from_anyone_else_are_ignored(behind_proxy):
    response = through(STRANGER).get("/api/auth/csrf/")

    assert not response.cookies["csrftoken"]["secure"]
    assert "Strict-Transport-Security" not in response


@pytest.mark.django_db
def test_without_a_trusted_proxy_no_forwarded_header_counts(settings):
    settings.DBS_MANAGER_TRUSTED_PROXIES = []

    response = through(PROXY).get("/api/auth/csrf/")

    assert not response.cookies["csrftoken"]["secure"]


@pytest.mark.django_db
def test_sign_in_attempts_are_counted_for_the_forwarded_client(behind_proxy):
    UserRepository().create(username="sara", password=PASSWORD)

    through(PROXY).post("/api/auth/login/", {"username": "sara", "password": "no"})

    [entry] = logged("auth.sign_in_failed")
    assert entry.remote_addr == CLIENT


@pytest.mark.django_db
def test_a_session_cookie_over_https_is_secure(behind_proxy):
    UserRepository().create(username="sara", password=PASSWORD)

    response = through(PROXY).post(
        "/api/auth/login/", {"username": "sara", "password": PASSWORD}
    )

    cookie = response.cookies["dbs_manager_session"]
    assert cookie["secure"] is True and cookie["httponly"] is True
