from __future__ import annotations

from datetime import timedelta

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from dbs.manager.accounts.models import Account
from dbs.manager.permissions import Role

BEFORE = ("dbs_manager", "0004_backupfile_failure")
AFTER = ("dbs_manager", "0005_accounts_security")


@pytest.fixture
def before_accounts():
    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE])
    apps = executor.loader.project_state([BEFORE]).apps
    yield apps.get_model("auth", "User")
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


def migrate_to(target):
    MigrationExecutor(connection).migrate([target])


@pytest.mark.django_db(transaction=True)
def test_the_oldest_account_becomes_master_and_the_others_admins(before_accounts):
    User = before_accounts
    now = timezone.now()
    for days, name in ((3, "omar"), (30, "sara"), (1, "nadia")):
        User.objects.create(
            username=name, password="!", date_joined=now - timedelta(days=days)
        )

    migrate_to(AFTER)

    roles = dict(Account.objects.values_list("user__username", "role"))
    assert roles == {"sara": Role.MASTER, "omar": Role.ADMIN, "nadia": Role.ADMIN}
    assert not Account.objects.filter(totp_enrolled_at__isnull=False).exists()
    assert all(
        account.password_changed_at > now - timedelta(minutes=5)
        for account in Account.objects.all()
    )


@pytest.mark.django_db(transaction=True)
def test_an_active_account_is_preferred_for_master(before_accounts):
    User = before_accounts
    now = timezone.now()
    User.objects.create(
        username="gone", password="!", is_active=False, date_joined=now - timedelta(9)
    )
    User.objects.create(username="sara", password="!", date_joined=now)

    migrate_to(AFTER)

    assert Account.objects.get(role=Role.MASTER).user.username == "sara"


@pytest.mark.django_db(transaction=True)
def test_an_installation_without_accounts_upgrades_cleanly(before_accounts):
    migrate_to(AFTER)

    assert not Account.objects.exists()
