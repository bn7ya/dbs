from __future__ import annotations

import time

import pytest
from rest_framework.test import APIClient

from dbs.manager.accounts import totp
from dbs.manager.accounts.models import Account, RecoveryCode
from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.accounts.services.pending import SINCE
from tests.manager.accounts.support import SECRET, code, enrolled, signed_in
from tests.manager.support import PASSWORD, logged

LOGIN = "/api/auth/login/"
CODE = "/api/auth/two-factor/"
ENROLLMENT = "/api/auth/two-factor/enrollment/"
CONFIRM = "/api/auth/two-factor/enrollment/confirm/"
ME = "/api/auth/me/"


@pytest.fixture
def sara(db):
    return UserRepository().create(username="sara", password=PASSWORD)


@pytest.fixture
def client():
    return APIClient()


def password_step(client, password=PASSWORD):
    return client.post(LOGIN, {"username": "sara", "password": password})


def error(response):
    return response.json()["error"]["code"]


@pytest.mark.django_db
def test_the_right_password_alone_does_not_sign_in(client, sara):
    enrolled(sara)

    response = password_step(client)

    assert response.json() == {"step": "code"}
    assert client.get(ME).status_code == 403
    assert client.get("/api/servers/").status_code == 403
    assert logged("auth.sign_in") == []


@pytest.mark.django_db
def test_an_account_without_two_factor_must_set_it_up(client, sara):
    assert password_step(client).json() == {"step": "enroll"}

    enrollment = client.post(ENROLLMENT).json()
    again = client.post(ENROLLMENT).json()

    assert enrollment["username"] == "sara" and enrollment["issuer"] == "DBS manager"
    assert enrollment["secret"] == again["secret"]
    assert enrollment["uri"].startswith("otpauth://totp/DBS%20manager%3Asara?")
    assert f"secret={enrollment['secret']}" in enrollment["uri"]
    assert client.get(ME).status_code == 403


@pytest.mark.django_db
def test_enrolling_with_a_current_code_signs_in_and_gives_ten_recovery_codes(
    client, sara
):
    password_step(client)
    secret = client.post(ENROLLMENT).json()["secret"]

    response = client.post(CONFIRM, {"code": code(secret)})

    assert response.status_code == 200
    body = response.json()
    assert body["identity"]["username"] == "sara"
    assert body["identity"]["two_factor"] is True
    assert body["identity"]["recovery_codes_left"] == 10
    assert len(body["recovery_codes"]) == len(set(body["recovery_codes"])) == 10
    assert client.get(ME).status_code == 200
    account = Account.objects.get(user=sara)
    assert secret.encode() not in bytes(account.totp_secret_sealed)
    stored = set(RecoveryCode.objects.values_list("digest", flat=True))
    assert not stored & set(body["recovery_codes"])
    assert [entry.target_name for entry in logged("auth.sign_in")] == ["sara"]
    assert len(logged("account.two_factor_enrolled")) == 1


@pytest.mark.django_db
def test_enrolling_with_a_wrong_code_keeps_the_account_out(client, sara):
    password_step(client)
    secret = client.post(ENROLLMENT).json()["secret"]

    refused = client.post(CONFIRM, {"code": code(secret, steps_ahead=5)})

    assert refused.status_code == 400 and error(refused) == "invalid_code"
    assert client.get(ME).status_code == 403
    assert not Account.objects.get(user=sara).has_two_factor


@pytest.mark.django_db
def test_an_enrolled_account_signs_in_with_its_code(client, sara):
    enrolled(sara)

    response = signed_in(client, "sara", PASSWORD)

    assert response.json()["username"] == "sara"
    assert client.get(ME).json()["two_factor"] is True


@pytest.mark.django_db
def test_a_code_is_accepted_once(client, sara):
    enrolled(sara)
    signed_in(client, "sara", PASSWORD)
    client.post("/api/auth/logout/")
    used = code(SECRET)

    password_step(client)
    replayed = client.post(CODE, {"code": used})

    assert replayed.status_code == 400 and error(replayed) == "invalid_code"
    assert client.get(ME).status_code == 403
    assert client.post(CODE, {"code": code(SECRET, steps_ahead=1)}).status_code == 200


@pytest.mark.django_db
def test_an_enrolled_account_cannot_enroll_again(client, sara):
    enrolled(sara)
    password_step(client)

    refused = client.post(ENROLLMENT)

    assert refused.status_code == 409 and error(refused) == "two_factor_enrolled"


@pytest.mark.django_db
def test_a_recovery_code_signs_in_once(client, sara):
    recovery = enrolled(sara)
    password_step(client)

    first = client.post(CODE, {"recovery_code": recovery[0].upper()})
    client.post("/api/auth/logout/")
    password_step(client)
    again = client.post(CODE, {"recovery_code": recovery[0]})

    assert first.status_code == 200
    assert first.json()["recovery_codes_left"] == 9
    assert again.status_code == 400 and error(again) == "invalid_code"
    assert len(logged("auth.recovery_code_used")) == 1


@pytest.mark.django_db
def test_a_code_without_a_password_first_is_refused(client, sara):
    enrolled(sara)

    refused = client.post(CODE, {"code": code(SECRET)})

    assert refused.status_code == 403 and error(refused) == "sign_in_expired"


@pytest.mark.django_db
def test_a_sign_in_left_waiting_too_long_expires(client, sara, settings):
    enrolled(sara)
    password_step(client)
    session = client.session
    session[SINCE] = time.time() - settings.AUTH_PENDING_SECONDS - 1
    session.save()

    refused = client.post(CODE, {"code": code(SECRET)})

    assert refused.status_code == 403 and error(refused) == "sign_in_expired"


@pytest.mark.django_db
def test_code_attempts_are_limited_like_passwords(client, sara, settings):
    settings.AUTH_FAILURES_PER_USER = 3
    enrolled(sara)
    password_step(client)
    wrong = code(SECRET, steps_ahead=10)
    for _ in range(3):
        assert error(client.post(CODE, {"code": wrong})) == "invalid_code"

    refused = client.post(CODE, {"code": code(SECRET)})

    assert refused.status_code == 429 and error(refused) == "too_many_attempts"
    failures = [entry.error_code for entry in logged("auth.sign_in_failed")]
    assert failures.count("invalid_code") == 3


@pytest.mark.django_db
def test_new_recovery_codes_need_the_password_and_replace_the_old_ones(client, sara):
    old = enrolled(sara)
    signed_in(client, "sara", PASSWORD)

    refused = client.post("/api/auth/recovery-codes/", {"password": "wrong"})
    fresh = client.post("/api/auth/recovery-codes/", {"password": PASSWORD})

    assert refused.status_code == 400 and error(refused) == "invalid_password"
    assert fresh.status_code == 200
    assert len(fresh.json()["recovery_codes"]) == 10
    client.post("/api/auth/logout/")
    password_step(client)
    assert error(client.post(CODE, {"recovery_code": old[1]})) == "invalid_code"
    assert (
        client.post(CODE, {"recovery_code": fresh.json()["recovery_codes"][0]})
    ).status_code == 200


@pytest.mark.django_db
def test_setup_leads_straight_into_enrollment(client):
    from dbs.manager.accounts.services.setup_service import write_token

    created = client.post(
        "/api/setup/",
        {"token": write_token(), "username": "sara", "password": PASSWORD},
    )

    assert created.status_code == 201
    assert created.json() == {"username": "sara", "step": "enroll"}
    assert client.get(ME).status_code == 403
    secret = client.post(ENROLLMENT).json()["secret"]
    confirmed = client.post(CONFIRM, {"code": totp.code_at(secret, time.time())})
    assert confirmed.status_code == 200
    assert client.get(ME).json()["role"] == "master"
