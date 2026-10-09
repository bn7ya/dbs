from __future__ import annotations

import pytest
from django.contrib.auth.models import AbstractBaseUser
from django.core.cache import cache
from rest_framework.test import APIClient

from dbs.manager.accounts.exceptions import InvalidPassword, TooManyAttempts
from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.accounts.services import AccountService
from dbs.manager.activity.repositories import ActivityRepository

PASSWORD = "correct-horse-battery-staple"
WRONG = "not-the-password"


@pytest.fixture(autouse=True)
def limits(settings) -> None:
    settings.AUTH_FAILURES_PER_USER = 3
    settings.AUTH_FAILURES_PER_ADDRESS = 5
    settings.AUTH_FAILURE_WINDOW = 900


@pytest.fixture
def sara(db):
    return UserRepository().create(username="sara", password=PASSWORD)


def sign_in(username: str, password: str, address: str = "203.0.113.7"):
    return APIClient(REMOTE_ADDR=address).post(
        "/api/auth/login/", {"username": username, "password": password}
    )


def code(response) -> str:
    return response.json()["error"]["code"]


@pytest.mark.django_db
def test_a_name_past_its_limit_is_refused_even_with_the_right_password(sara):
    for _ in range(3):
        assert code(sign_in("sara", WRONG)) == "authentication_failed"

    refused = sign_in("sara", PASSWORD)

    assert refused.status_code == 429
    assert code(refused) == "too_many_attempts"
    assert refused.json()["error"]["message"] == (
        "Too many attempts. Wait a few minutes and try again."
    )
    assert refused["Retry-After"] == "900"


@pytest.mark.django_db
def test_the_name_limit_ignores_case_and_holds_across_addresses(sara):
    for address in ("203.0.113.1", "203.0.113.2", "203.0.113.3"):
        sign_in("SARA", WRONG, address)

    assert sign_in("sara", PASSWORD, "198.51.100.9").status_code == 429


@pytest.mark.django_db
def test_an_address_past_its_limit_is_refused_for_every_name(sara):
    for number in range(5):
        sign_in(f"nobody-{number}", WRONG)

    assert code(sign_in("sara", PASSWORD)) == "too_many_attempts"
    assert sign_in("sara", PASSWORD, "198.51.100.9").status_code == 200


@pytest.mark.django_db
def test_signing_in_clears_the_name_but_not_the_address(sara):
    sign_in("sara", WRONG)
    sign_in("sara", WRONG)
    assert sign_in("sara", PASSWORD).status_code == 200

    for number in range(2):
        sign_in(f"nobody-{number}", WRONG)

    assert sign_in("sara", WRONG).status_code == 403
    assert code(sign_in("sara", PASSWORD)) == "too_many_attempts"


@pytest.mark.django_db
def test_a_refusal_for_too_many_attempts_is_in_the_activity_log(sara):
    for _ in range(3):
        sign_in("sara", WRONG)
    sign_in("sara", PASSWORD)

    refused = [
        entry
        for entry in ActivityRepository().filtered(action="auth.sign_in_failed")
        if entry.error_code == "too_many_attempts"
    ]
    assert [(entry.target_name, entry.status) for entry in refused] == [
        ("sara", "failed")
    ]


@pytest.mark.django_db
def test_a_password_asked_for_again_is_limited_per_user(sara):
    service = AccountService(sara)
    for _ in range(3):
        with pytest.raises(InvalidPassword):
            service.confirm_password(WRONG)

    with pytest.raises(TooManyAttempts):
        service.confirm_password(PASSWORD)


@pytest.mark.django_db
def test_the_limit_for_a_password_asked_for_again_is_the_users_own(sara):
    other = UserRepository().create(username="omar", password=PASSWORD)
    for _ in range(3):
        with pytest.raises(InvalidPassword):
            AccountService(sara).confirm_password(WRONG)

    AccountService(other).confirm_password(PASSWORD)


@pytest.mark.django_db
def test_the_right_password_asked_for_again_clears_the_count(sara):
    service = AccountService(sara)
    for _ in range(2):
        with pytest.raises(InvalidPassword):
            service.confirm_password(WRONG)
    service.confirm_password(PASSWORD)

    for _ in range(2):
        with pytest.raises(InvalidPassword):
            service.confirm_password(WRONG)
    service.confirm_password(PASSWORD)


@pytest.mark.django_db
def test_an_attempt_is_counted_before_its_password_is_checked(sara, monkeypatch):
    seen = []
    check = AbstractBaseUser.check_password

    def checking(user, password):
        seen.append(cache.get(f"accounts:failures:confirm:user:{user.pk}"))
        return check(user, password)

    monkeypatch.setattr(AbstractBaseUser, "check_password", checking)
    service = AccountService(sara)
    for _ in range(2):
        with pytest.raises(InvalidPassword):
            service.confirm_password(WRONG)

    assert seen == [1, 2]


@pytest.mark.django_db
def test_signing_in_often_from_one_address_is_never_limited(sara):
    for _ in range(8):
        assert sign_in("sara", PASSWORD).status_code == 200


@pytest.mark.django_db
def test_an_attempt_refused_unchecked_does_not_count_against_the_address(sara):
    omar = UserRepository().create(username="omar", password=PASSWORD)
    for _ in range(3):
        sign_in("sara", WRONG)
    for _ in range(4):
        assert sign_in("sara", PASSWORD).status_code == 429

    assert sign_in(omar.username, PASSWORD).status_code == 200
