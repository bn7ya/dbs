from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from dbs.manager.accounts.models import Account
from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.permissions import Role
from tests.manager.accounts.support import SECRET, code, enrolled, signed_in
from tests.manager.support import PASSWORD, logged

ACCOUNTS = "/api/accounts/"
NEW_PASSWORD = "a-brand-new-long-passphrase"


@pytest.fixture
def master(db):
    return UserRepository().create_superuser(username="maria", password=PASSWORD)


@pytest.fixture
def omar(db):
    return UserRepository().create(username="omar", password=PASSWORD, role=Role.ADMIN)


def client_for(user):
    client = APIClient()
    client.force_login(user)
    return client


def error(response):
    return response.json()["error"]


@pytest.mark.django_db
def test_the_master_lists_every_account(master, omar, django_user_model):
    django_user_model.objects.create_user(username="zaid", password=PASSWORD)

    listed = client_for(master).get(ACCOUNTS).json()

    assert [(row["username"], row["role"]) for row in listed] == [
        ("maria", Role.MASTER),
        ("omar", Role.ADMIN),
        ("zaid", Role.VIEWER),
    ]
    assert listed[1]["is_active"] is True
    assert listed[1]["two_factor"] is False
    assert listed[1]["password_expires_at"]


@pytest.mark.django_db
def test_only_the_master_manages_accounts(master, omar):
    admin = client_for(omar)

    for refused in (
        admin.get(ACCOUNTS),
        admin.post(
            ACCOUNTS, {"username": "nadia", "password": NEW_PASSWORD, "role": "viewer"}
        ),
        admin.patch(f"{ACCOUNTS}{master.pk}/", {"role": "viewer"}),
        admin.post(f"{ACCOUNTS}{master.pk}/two-factor/reset/"),
    ):
        assert refused.status_code == 403
        assert error(refused)["code"] == "role_required"


@pytest.mark.django_db
def test_the_master_creates_an_account_that_must_choose_its_own_password(master):
    created = client_for(master).post(
        ACCOUNTS, {"username": "nadia", "password": NEW_PASSWORD, "role": "operator"}
    )

    assert created.status_code == 201
    assert created.json()["role"] == Role.OPERATOR
    assert created.json()["password_change_required"] is True
    nadia = UserRepository().find_by_username("nadia")
    assert nadia.check_password(NEW_PASSWORD) and not nadia.is_superuser
    assert logged("account.create")[0].target_name == "nadia"


@pytest.mark.django_db
def test_creating_an_account_checks_its_name_role_and_password(master, omar):
    master_client = client_for(master)

    taken = master_client.post(
        ACCOUNTS, {"username": "OMAR", "password": NEW_PASSWORD, "role": "viewer"}
    )
    weak = master_client.post(
        ACCOUNTS, {"username": "nadia", "password": "123", "role": "viewer"}
    )
    second_master = master_client.post(
        ACCOUNTS, {"username": "nadia", "password": NEW_PASSWORD, "role": "master"}
    )

    assert error(taken)["fields"] == {"username": ["name_taken"]}
    assert "password_too_short" in error(weak)["fields"]["password"]
    assert error(second_master)["fields"] == {"role": ["invalid_choice"]}


@pytest.mark.django_db
def test_the_master_sets_roles_and_switches_accounts_off_and_on(master, omar):
    master_client = client_for(master)
    url = f"{ACCOUNTS}{omar.pk}/"

    demoted = master_client.patch(url, {"role": "viewer"})
    disabled = master_client.patch(url, {"is_active": False})
    enabled = master_client.patch(url, {"is_active": True})

    assert demoted.json()["role"] == Role.VIEWER
    assert disabled.json()["is_active"] is False
    assert enabled.json()["is_active"] is True
    assert [entry.action for entry in logged()][:3] == [
        "account.enable",
        "account.disable",
        "account.role",
    ]


@pytest.mark.django_db
def test_a_disabled_account_loses_its_session(master, omar):
    omars = client_for(omar)
    assert omars.get("/api/auth/me/").status_code == 200

    client_for(master).patch(f"{ACCOUNTS}{omar.pk}/", {"is_active": False})

    assert omars.get("/api/auth/me/").status_code == 403


@pytest.mark.django_db
def test_the_master_cannot_be_demoted_or_disabled(master):
    master_client = client_for(master)

    demoted = master_client.patch(f"{ACCOUNTS}{master.pk}/", {"role": "admin"})
    disabled = master_client.patch(f"{ACCOUNTS}{master.pk}/", {"is_active": False})

    assert demoted.status_code == 409 and error(demoted)["code"] == "master_protected"
    assert error(disabled)["code"] == "master_protected"
    assert Account.objects.get(user=master).role == Role.MASTER


@pytest.mark.django_db
def test_resetting_two_factor_makes_the_account_set_it_up_again(master, omar):
    enrolled(omar)

    reset = client_for(master).post(f"{ACCOUNTS}{omar.pk}/two-factor/reset/")
    step = APIClient().post(
        "/api/auth/login/", {"username": "omar", "password": PASSWORD}
    )

    assert reset.json()["two_factor"] is False
    assert reset.json()["recovery_codes_left"] == 0
    assert step.json() == {"step": "enroll"}


@pytest.mark.django_db
def test_forcing_a_password_change_restricts_the_next_session(master, omar):
    client_for(master).post(f"{ACCOUNTS}{omar.pk}/password/expire/")

    omars = client_for(omar)

    assert error(omars.get("/api/servers/"))["code"] == "password_change_required"
    assert omars.get("/api/auth/me/").json()["password_change_required"] is True


@pytest.mark.django_db
def test_handing_over_the_master_role_needs_the_password_and_a_code(master, omar):
    enrolled(master)
    master_client = client_for(master)
    url = f"{ACCOUNTS}{omar.pk}/master/"

    wrong_password = master_client.post(url, {"password": "wrong", "code": code()})
    wrong_code = master_client.post(
        url, {"password": PASSWORD, "code": code(SECRET, steps_ahead=9)}
    )
    handed = master_client.post(url, {"password": PASSWORD, "code": code()})

    assert error(wrong_password)["code"] == "invalid_password"
    assert error(wrong_code)["code"] == "invalid_code"
    assert handed.status_code == 200 and handed.json()["role"] == Role.MASTER
    assert Account.objects.get(user=master).role == Role.ADMIN
    assert error(master_client.get(ACCOUNTS))["code"] == "role_required"
    assert logged("account.master")[0].target_name == "omar"


@pytest.mark.django_db
def test_the_master_role_goes_only_to_an_active_account(master, omar):
    enrolled(master)
    UserRepository().deactivate(omar)

    refused = client_for(master).post(
        f"{ACCOUNTS}{omar.pk}/master/", {"password": PASSWORD, "code": code()}
    )

    assert error(refused)["code"] == "account_inactive"


@pytest.mark.django_db
def test_a_new_account_signs_in_sets_up_two_factor_then_must_change_password(
    master,
):
    client_for(master).post(
        ACCOUNTS, {"username": "nadia", "password": NEW_PASSWORD, "role": "viewer"}
    )
    nadia = APIClient()

    nadia.post("/api/auth/login/", {"username": "nadia", "password": NEW_PASSWORD})
    secret = nadia.post("/api/auth/two-factor/enrollment/").json()["secret"]
    nadia.post("/api/auth/two-factor/enrollment/confirm/", {"code": code(secret)})

    assert error(nadia.get("/api/servers/"))["code"] == "password_change_required"
    changed = nadia.post(
        "/api/auth/password/",
        {"current_password": NEW_PASSWORD, "new_password": PASSWORD},
    )
    assert changed.status_code == 200
    assert changed.json()["password_change_required"] is False
    assert nadia.get("/api/servers/").status_code == 200


@pytest.mark.django_db
def test_the_master_signs_in_with_two_factor_like_anyone(master):
    enrolled(master)

    response = signed_in(APIClient(), "maria", PASSWORD)

    assert response.json()["role"] == Role.MASTER
    assert "accounts.manage" in response.json()["capabilities"]
