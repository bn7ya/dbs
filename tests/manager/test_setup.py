import pytest
from rest_framework.test import APIClient

from dbs import leases
from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.accounts.services import setup_service
from dbs.manager.accounts.services.setup_service import token_path, write_token
from dbs.manager.conf import SETUP_LEASE
from tests.manager.support import PASSWORD, logged

SETUP = "/api/setup/"


@pytest.fixture
def token(db):
    return write_token()


def post(client, **body):
    return client.post(SETUP, body, format="json")


@pytest.mark.django_db
def test_setup_is_needed_until_an_account_exists(anonymous):
    assert anonymous.get(SETUP).json() == {"needed": True}

    UserRepository().create(username="sara", password=PASSWORD)

    assert anonymous.get(SETUP).json() == {"needed": False}


def test_the_token_file_is_private(token):
    assert token_path().read_text() == token
    assert token_path().stat().st_mode & 0o777 == 0o600


def test_setup_creates_the_first_account_and_signs_it_in(anonymous, token):
    response = post(anonymous, token=token, username="sara", password=PASSWORD)

    assert response.status_code == 201
    assert response.json() == {"username": "sara"}
    user = UserRepository().find_by_username("sara")
    assert user.is_superuser and user.check_password(PASSWORD)
    assert anonymous.get("/api/auth/me/").json()["username"] == "sara"
    assert not token_path().exists()
    [entry] = logged("account.setup")
    assert entry.actor == user and entry.target_name == "sara"


def test_setup_happens_once(anonymous, token):
    assert (
        post(anonymous, token=token, username="sara", password=PASSWORD).status_code
        == 201
    )
    write_token()

    response = post(
        APIClient(), token=token_path().read_text(), username="omar", password=PASSWORD
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "setup_done"
    assert UserRepository().find_by_username("omar") is None


def test_an_existing_account_ends_setup_even_with_the_right_token(anonymous, token):
    UserRepository().create(username="sara", password=PASSWORD)

    response = post(anonymous, token=token, username="omar", password=PASSWORD)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "setup_done"


def test_a_wrong_token_is_refused(anonymous, token):
    response = post(
        anonymous, token="not-the-token", username="sara", password=PASSWORD
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "setup_token_invalid"
    assert not UserRepository().any_exist()
    assert token_path().exists()


@pytest.mark.django_db
def test_without_a_token_file_every_token_is_refused(anonymous):
    response = post(anonymous, token="anything", username="sara", password=PASSWORD)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "setup_token_invalid"


def test_a_weak_password_is_refused_in_the_error_envelope(anonymous, token):
    response = post(anonymous, token=token, username="sara", password="123")

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid"
    assert set(error["fields"]["password"]) == {
        "password_too_short",
        "password_entirely_numeric",
        "password_too_common",
    }
    assert not UserRepository().any_exist()


def test_a_setup_already_under_way_holds_off_another(anonymous, token, monkeypatch):
    monkeypatch.setattr(setup_service, "LEASE_WAIT_SECONDS", 0.1)
    assert leases.acquire(SETUP_LEASE, "another-request", 60)

    response = post(anonymous, token=token, username="sara", password=PASSWORD)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "setup_done"
    assert not UserRepository().any_exist()
    leases.release(SETUP_LEASE, "another-request")
    assert (
        post(anonymous, token=token, username="sara", password=PASSWORD).status_code
        == 201
    )


def test_setup_lets_its_lease_go_whatever_happens(anonymous, token):
    post(anonymous, token="wrong", username="sara", password=PASSWORD)

    assert leases.holder(SETUP_LEASE) is None


def test_a_password_like_the_username_is_refused_by_its_own_code(anonymous, token):
    response = post(
        anonymous, token=token, username="wilhelmina", password="wilhelmina-77"
    )

    assert response.json()["error"]["fields"]["password"] == ["password_too_similar"]


def test_a_username_django_would_refuse_is_a_field_error(anonymous, token):
    response = post(anonymous, token=token, username="no spaces", password=PASSWORD)

    assert response.status_code == 400
    assert list(response.json()["error"]["fields"]) == ["username"]
