from __future__ import annotations

import pytest

from dbs.manager.backups.models import BackupPlan
from dbs.manager.backups.services import BackupPlanService
from dbs.manager.servers.exceptions import HostKeyNotConfirmed, HostKeyRejected
from dbs.manager.servers.gateways import parse_host_key
from dbs.manager.servers.services import HostKeyConfirmationService
from tests.manager.servers.support import PASSWORD, host_key_line
from tests.manager.support import logged

FETCH_HOST_KEY = "dbs.manager.servers.services.server_service.fetch_host_key"


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


@pytest.fixture
def held(monkeypatch, admin):
    key = parse_host_key(host_key_line())
    monkeypatch.setattr(FETCH_HOST_KEY, lambda host, port: key)
    return HostKeyConfirmationService(admin).request("10.0.0.5", 22)


@pytest.mark.django_db
def test_a_person_confirms_a_host_key_at_the_terminal(terminal, typing, admin, held):
    typing.append("y")

    ran = terminal("server", "confirm-host-key", held.id)

    assert ran.code == 0, ran.err
    assert held.fingerprint in ran.out and "10.0.0.5:22" in ran.out
    confirmations = HostKeyConfirmationService(admin)
    assert confirmations.approved(held.id, "10.0.0.5", 22) == held.line
    assert [entry.actor for entry in logged("server.host_key_confirm")] == [admin]


@pytest.mark.django_db
@pytest.mark.parametrize("answer", ["n", "", "yes please"])
def test_anything_but_yes_rejects_it(terminal, typing, admin, held, answer):
    typing.append(answer)

    ran = terminal("server", "confirm-host-key", held.id)

    assert ran.code == 1
    with pytest.raises(HostKeyRejected):
        HostKeyConfirmationService(admin).approved(held.id, "10.0.0.5", 22)


@pytest.mark.django_db
def test_a_script_cannot_confirm_a_host_key(terminal, admin, held):
    ran = terminal("server", "confirm-host-key", held.id, stdin="y\n")

    assert ran.code == 1 and "run it in a terminal" in ran.err
    with pytest.raises(HostKeyNotConfirmed):
        HostKeyConfirmationService(admin).approved(held.id, "10.0.0.5", 22)


@pytest.mark.django_db
def test_an_unknown_confirmation_is_named(terminal, admin):
    ran = terminal("server", "confirm-host-key", "0badc0de")

    assert ran.code == 1 and "10 minutes" in ran.err
