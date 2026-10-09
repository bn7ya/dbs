from __future__ import annotations

import pytest

from dbs.manager.accounts.exceptions import InvalidPassword
from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.accounts.services import AccountService

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def member(db):
    return UserRepository().create(username="sara", password=PASSWORD)


@pytest.mark.django_db
def test_the_users_own_password_is_confirmed(member):
    assert AccountService(member).confirm_password(PASSWORD) is None


@pytest.mark.django_db
@pytest.mark.parametrize("password", ["wrong", "", PASSWORD.upper()])
def test_any_other_password_is_refused(member, password):
    with pytest.raises(InvalidPassword) as refused:
        AccountService(member).confirm_password(password)

    assert refused.value.default_code == "invalid_password"
    assert refused.value.status_code == 400


def test_there_is_no_password_to_confirm_without_a_user():
    with pytest.raises(InvalidPassword):
        AccountService().confirm_password(PASSWORD)
