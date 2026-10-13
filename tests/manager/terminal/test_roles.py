from datetime import timedelta

import pytest
from django.utils import timezone

from dbs.manager.accounts.models import Account
from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.permissions import Role
from tests.manager.servers.support import PASSWORD


@pytest.fixture
def viewer(db):
    return UserRepository().create(username="vera", password=PASSWORD, role=Role.VIEWER)


@pytest.mark.django_db
def test_acting_as_a_viewer_reads_but_never_changes(
    terminal, admin, viewer, make_server
):
    make_server()

    listed = terminal("server", "list", "--as", "vera")
    taken = terminal("backup", "take", "web-1", "--as", "vera")
    removed = terminal("server", "remove", "web-1", "--as", "vera", "--yes")

    assert listed.code == 0 and "web-1" in listed.out
    assert taken.code == 1
    assert "This needs the operator role or higher; your account is a viewer." in (
        taken.out
    )
    assert removed.code == 1
    assert "This needs the admin role or higher; your account is a viewer." in (
        removed.err
    )


@pytest.mark.django_db
def test_an_expired_password_warns_but_does_not_block(terminal, admin):
    Account.objects.filter(user=admin).update(
        password_changed_at=timezone.now() - timedelta(days=31)
    )

    ran = terminal("server", "list", "--as", "sara")

    assert ran.code == 0
    assert "the password of sara has expired" in ran.err
    assert "django_dbs password sara" in ran.err


@pytest.mark.django_db
def test_a_current_password_prints_no_warning(terminal, admin):
    assert "expired" not in terminal("server", "list").err
