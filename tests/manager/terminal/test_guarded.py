from __future__ import annotations

import pytest

from dbs.manager.backups.models import BackupPlan
from dbs.manager.backups.services import BackupPlanService
from tests.manager.servers.support import PASSWORD


@pytest.fixture
def plan(admin, make_server):
    server = make_server(name="shop")
    return BackupPlanService(admin).create(
        server=server.pk, name="nightly", kind="dbs", keep=3, keep_remote=2
    )


@pytest.mark.django_db
def test_keeping_fewer_asks_for_the_account_password(terminal, plan):
    refused = terminal("plan", "edit", plan.pk, "--keep", "2")
    wrong = terminal(
        "plan", "edit", plan.pk, "--keep-remote", "0", "--password-stdin", stdin="no\n"
    )
    saved = terminal(
        "plan",
        "edit",
        plan.pk,
        "--keep",
        "1",
        "--keep-remote",
        "0",
        "--password-stdin",
        stdin=f"{PASSWORD}\n",
    )

    assert refused.code == 1 and "--password-stdin" in refused.err
    assert wrong.code == 1
    assert saved.code == 0, saved.err
    stored = BackupPlan.objects.get(pk=plan.pk)
    assert (stored.keep, stored.keep_remote) == (1, 0)


@pytest.mark.django_db
def test_keeping_more_asks_nothing(terminal, plan):
    ran = terminal("plan", "edit", plan.pk, "--keep", "5", "--keep-remote", "5")

    assert ran.code == 0, ran.err
    stored = BackupPlan.objects.get(pk=plan.pk)
    assert (stored.keep, stored.keep_remote) == (5, 5)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "option", [("--keep", "0"), ("--keep", "6"), ("--keep-remote", "6")]
)
def test_the_terminal_keeps_one_to_five(terminal, capsys, plan, option):
    with pytest.raises(SystemExit) as stopped:
        terminal("plan", "add", "shop", "weekly", "--kind", "dbs", *option)

    assert stopped.value.code == 2
    assert "invalid choice" in capsys.readouterr().err
    assert BackupPlan.objects.count() == 1
