from __future__ import annotations

from collections import Counter
from functools import lru_cache
from uuid import uuid4

import pytest
from django.db import transaction

from dbs.manager.backups.models import BackupFile, BackupPlan
from dbs.manager.backups.repositories import BackupFileRepository
from dbs.manager.backups.services import BackupPlanService
from dbs.manager.mcp.tools import KEEPS_FEWER
from tests.manager.backups.support import BackupHost
from tests.manager.servers.support import (
    BACKUP_PASSPHRASE,
    PASSWORD,
    connecting_to,
    dbs_backup,
)

CONNECT = "dbs.manager.servers.services.connection_service.connect"
SEEDED = 3
DEPTH = 4
ONE_OFF = ""


@lru_cache(maxsize=None)
def made_backup() -> bytes:
    return dbs_backup(BACKUP_PASSPHRASE)


@pytest.fixture
def host(monkeypatch, tmp_path):
    found = BackupHost(content=made_backup(), root=tmp_path / "server")
    monkeypatch.setattr(CONNECT, connecting_to(found))
    return found


def plan_named(server, name):
    return BackupPlan.objects.filter(server=server, name=name).first()


def updating(name, change):
    def step(mcp, server):
        plan = plan_named(server, name)
        if plan is None:
            return None
        return mcp("update_plan", plan=str(plan.pk), **change(plan))

    return step


def running(name):
    def step(mcp, server):
        plan = plan_named(server, name)
        if plan is None:
            return None
        return mcp("run_plan", plan=str(plan.pk))

    return step


def adding(name, **fields):
    def step(mcp, server):
        return mcp("add_plan", server=server.name, name=name, kind="dbs", **fields)

    return step


def taking(mcp, server):
    return mcp("take_backups", servers=[server.name])


STEPS = {
    "run nightly": running("nightly"),
    "nightly keeps 1": updating("nightly", lambda plan: {"keep": 1}),
    "nightly keeps one fewer": updating(
        "nightly", lambda plan: {"keep": plan.keep - 1}
    ),
    "nightly keeps one more": updating("nightly", lambda plan: {"keep": plan.keep + 1}),
    "nightly keeps none on the server": updating(
        "nightly", lambda plan: {"keep_remote": 0}
    ),
    "nightly keeps one more on the server": updating(
        "nightly", lambda plan: {"keep_remote": plan.keep_remote + 1}
    ),
    "nightly keeps one more here and one fewer there": updating(
        "nightly",
        lambda plan: {"keep": plan.keep + 1, "keep_remote": plan.keep_remote - 1},
    ),
    "add spare": adding("spare", keep=1, keep_remote=0),
    "run spare": running("spare"),
    "spare keeps one more": updating("spare", lambda plan: {"keep": plan.keep + 1}),
    "rename spare like nightly": updating("spare", lambda plan: {"name": "Nightly"}),
    "add a plan named like nightly": adding("Nightly!", keep=1, keep_remote=0),
    "take a one-off backup": taking,
}


def seeded(admin, server):
    plan = BackupPlanService(admin).create(
        server=server.pk,
        name="nightly",
        kind="dbs",
        keep=SEEDED,
        keep_remote=2,
        account_password=PASSWORD,
    )
    for ordinal in range(SEEDED):
        BackupFileRepository().create(
            created_by=admin,
            server=server,
            plan=plan,
            kind=BackupFile.Kind.DBS,
            name=f"seed-{ordinal}.dbs",
            size=1,
            sha256="0" * 64,
            storage_path=f"seed/{uuid4()}.dbs",
            validation=BackupFile.Validation.STRUCTURE_OK,
        )
    return plan


def snapshot(server):
    files = Counter(
        BackupFile.objects.filter(server=server).values_list("plan__name", flat=True)
    )
    plans = {
        plan.name: (plan.keep, plan.keep_remote, files[plan.name])
        for plan in BackupPlan.objects.filter(server=server)
    }
    return frozenset({**plans, ONE_OFF: (0, 0, files[None])}.items())


def keeps_at_least(before, after):
    kept = dict(after)
    return all(
        name in kept and all(now >= then for now, then in zip(kept[name], counts))
        for name, counts in before
    )


@pytest.mark.django_db
def test_no_sequence_of_plan_tools_leaves_fewer_backups(
    mcp, admin, host, make_server, django_capture_on_commit_callbacks
):
    server = make_server(name="shop")
    seeded(admin, server)
    explored = set()
    refusals = Counter()

    def explore(path, remaining):
        state = snapshot(server)
        if remaining == 0 or (state, remaining) in explored:
            return
        explored.add((state, remaining))
        for name, step in STEPS.items():
            with transaction.atomic():
                with django_capture_on_commit_callbacks(execute=True):
                    called = step(mcp, server)
                after = snapshot(server)
                assert keeps_at_least(state, after), [*path, name]
                if called is not None and not called.ok:
                    refusals[called.text] += 1
                    assert after == state, [*path, name]
                else:
                    explore([*path, name], remaining - 1)
                transaction.set_rollback(True)

    explore([], DEPTH)

    assert refusals[KEEPS_FEWER] > 0
    assert any(text.startswith("name: ") for text in refusals)
    assert len(host.takes) > DEPTH


@pytest.mark.django_db(transaction=True)
def test_only_the_password_lets_a_plan_keep_fewer(mcp, api, admin, host, make_server):
    server = make_server(name="shop")
    plan = seeded(admin, server)

    refused = mcp("update_plan", plan=str(plan.pk), keep=1)
    mcp("run_plan", plan=str(plan.pk))
    after_refusal = BackupFileRepository().alive_for_plan(plan.pk).count()
    api.patch(
        f"/api/backups/plans/{plan.pk}/",
        {"keep": 1, "account_password": PASSWORD},
        format="json",
    )
    mcp("run_plan", plan=str(plan.pk))

    assert not refused.ok and refused.text == KEEPS_FEWER
    assert after_refusal == SEEDED
    [kept] = BackupFileRepository().alive_for_plan(plan.pk)
    newest = BackupFile.objects.filter(plan=plan).latest("created_at")
    assert kept.pk == newest.pk
    assert kept.validation == BackupFile.Validation.VERIFIED
