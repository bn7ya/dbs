from __future__ import annotations

import io
import sys
from dataclasses import dataclass

import pytest

from dbs.manager import cli
from dbs.manager.accounts.models import Account
from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.permissions import Role
from tests.manager.accounts.support import enrolled
from tests.manager.support import PASSWORD, logged

NEW_PASSWORD = "a-brand-new-long-passphrase"


@dataclass
class Ran:
    code: int
    out: str
    err: str


@pytest.fixture
def command(monkeypatch, capsys, db):
    monkeypatch.setattr(cli, "setup_django", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "resolve", lambda args: None)

    def run(*argv, stdin=""):
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
        code = cli.main(list(argv))
        captured = capsys.readouterr()
        return Ran(code, captured.out, captured.err)

    return run


def role_of(name):
    return Account.objects.get(user__username=name).role


def test_the_first_account_is_the_master(command):
    ran = command("createuser", "maria", "--password-stdin", stdin=f"{PASSWORD}\n")

    assert ran.code == 0, ran.err
    assert "the master account" in ran.out
    assert role_of("maria") == Role.MASTER
    assert not Account.objects.get(user__username="maria").password_change_required


def test_a_later_account_needs_a_role_and_changes_its_password_first(command):
    command("createuser", "maria", "--password-stdin", stdin=f"{PASSWORD}\n")

    missing = command("createuser", "omar", "--password-stdin", stdin=f"{PASSWORD}\n")
    second_master = command(
        "createuser", "omar", "--role", "master", "--password-stdin", stdin=PASSWORD
    )
    added = command(
        "createuser",
        "omar",
        "--role",
        "operator",
        "--password-stdin",
        stdin=f"{PASSWORD}\n",
    )

    assert missing.code == 1 and "--role" in missing.err
    assert second_master.code == 1 and "account role omar master" in second_master.err
    assert added.code == 0 and "as operator" in added.out
    assert role_of("omar") == Role.OPERATOR
    assert Account.objects.get(user__username="omar").password_change_required


def test_account_list_shows_roles_and_two_factor(command):
    maria = UserRepository().create_superuser(username="maria", password=PASSWORD)
    UserRepository().create(username="omar", password=PASSWORD, role=Role.VIEWER)
    enrolled(maria)

    ran = command("account", "list")

    lines = ran.out.splitlines()
    assert lines[0].split() == [
        "NAME",
        "ROLE",
        "ACTIVE",
        "TWO-FACTOR",
        "PASSWORD",
        "EXPIRES",
    ]
    assert lines[1].split()[:4] == ["maria", "master", "yes", "yes"]
    assert lines[2].split()[:4] == ["omar", "viewer", "yes", "no"]


def test_account_role_sets_a_role_and_hands_over_the_master(command):
    UserRepository().create_superuser(username="maria", password=PASSWORD)
    UserRepository().create(username="omar", password=PASSWORD, role=Role.VIEWER)

    promoted = command("account", "role", "omar", "admin")
    handed = command("account", "role", "omar", "master")
    demoted = command("account", "role", "omar", "viewer")

    assert promoted.code == 0 and "omar is now admin" in promoted.out
    assert handed.code == 0 and "omar is now the master account" in handed.out
    assert role_of("omar") == Role.MASTER and role_of("maria") == Role.ADMIN
    assert demoted.code == 1 and "master account cannot be demoted" in demoted.err
    assert logged("account.master")[0].target_name == "omar"


def test_account_disable_and_enable_switch_sign_in(command):
    UserRepository().create_superuser(username="maria", password=PASSWORD)
    omar = UserRepository().create(username="omar", password=PASSWORD)

    disabled = command("account", "disable", "omar")
    omar.refresh_from_db()
    off = omar.is_active
    enabled = command("account", "enable", "omar")
    omar.refresh_from_db()
    master = command("account", "disable", "maria")

    assert disabled.code == 0 and not off
    assert enabled.code == 0 and omar.is_active
    assert master.code == 1 and "master account cannot be" in master.err


def test_reset_2fa_works_even_on_the_master(command):
    maria = UserRepository().create_superuser(username="maria", password=PASSWORD)
    enrolled(maria)

    ran = command("account", "reset-2fa", "maria")

    assert ran.code == 0
    assert not Account.objects.get(user=maria).has_two_factor


def test_an_unknown_account_is_named(command):
    ran = command("account", "disable", "nadia")

    assert ran.code == 1 and "no account named 'nadia'" in ran.err


def test_password_resets_the_thirty_days_and_lifts_a_forced_change(command):
    from datetime import timedelta

    from django.utils import timezone

    omar = UserRepository().create(username="omar", password=PASSWORD)
    Account.objects.filter(user=omar).update(
        password_changed_at=timezone.now() - timedelta(days=60),
        password_change_required=True,
    )

    ran = command("password", "omar", "--password-stdin", stdin=f"{NEW_PASSWORD}\n")

    account = Account.objects.get(user=omar)
    assert ran.code == 0, ran.err
    assert not account.password_change_required
    assert account.password_changed_at > timezone.now() - timedelta(minutes=1)
