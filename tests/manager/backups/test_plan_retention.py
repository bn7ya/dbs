from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest
from django.apps import apps
from django.core.exceptions import ValidationError

from dbs.engine import restore
from dbs.manager import transfer
from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.backups.models import BackupPlan
from dbs.manager.backups.repositories import BackupFileRepository
from tests.manager.servers.support import PASSWORD

PLANS = "/api/backups/plans/"
MIGRATION = "dbs.manager.migrations.0006_plan_retention_limits"


def url(plan) -> str:
    return f"{PLANS}{plan.pk}/"


def logged(action: str):
    return list(ActivityRepository().filtered(action=action))


@pytest.mark.django_db
def test_a_plan_keeps_five_here_and_none_on_the_server_unless_told(api, server):
    plan = api.post(
        PLANS,
        {"server": str(server.pk), "name": "nightly", "kind": "dbs"},
        format="json",
    ).json()

    assert (plan["keep"], plan["keep_remote"]) == (5, 0)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("fields", "errors"),
    [
        ({"keep": 0}, {"keep": ["min_value"]}),
        ({"keep": 6}, {"keep": ["max_value"]}),
        ({"keep_remote": -1}, {"keep_remote": ["min_value"]}),
        ({"keep_remote": 6}, {"keep_remote": ["max_value"]}),
    ],
)
def test_a_plan_keeps_one_to_five_here_and_up_to_five_there(
    api, server, fields, errors
):
    body = {"server": str(server.pk), "name": "nightly", "kind": "dbs", **fields}

    response = api.post(PLANS, body, format="json")

    assert response.json()["error"]["fields"] == errors


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "value"), [("keep", 0), ("keep", 6), ("keep_remote", 6)]
)
def test_the_model_refuses_retention_out_of_range(make_plan, field, value):
    plan = make_plan()
    setattr(plan, field, value)

    with pytest.raises(ValidationError) as refused:
        plan.full_clean()

    assert list(refused.value.message_dict) == [field]


@pytest.mark.django_db
def test_the_migration_clamps_what_was_kept_before_into_range(make_plan):
    many = make_plan(name="many")
    none = make_plan(name="none")
    make_plan(name="fine", keep=3, keep_remote=2)
    BackupPlan.objects.filter(pk=many.pk).update(keep=365, keep_remote=30)
    BackupPlan.objects.filter(pk=none.pk).update(keep=0, keep_remote=0)
    many.delete()

    importlib.import_module(MIGRATION).clamp_retention(apps, None)

    kept = {
        plan.name: (plan.keep, plan.keep_remote)
        for plan in BackupPlan.all_objects.all()
    }
    assert kept == {"many": (5, 5), "none": (1, 0), "fine": (3, 2)}


@pytest.mark.django_db
def test_an_import_keeps_what_an_older_export_kept_in_range(
    monkeypatch, make_plan, tmp_path
):
    plan = make_plan()
    exported = tmp_path / "manager.dbs"
    exported.write_bytes(b"an export")

    def restored(data, passphrase, **options):
        BackupPlan.objects.filter(pk=plan.pk).update(keep=30, keep_remote=9)
        return SimpleNamespace(records_loaded=1, healed=False)

    monkeypatch.setattr(restore, "restore_backup", restored)
    monkeypatch.setattr(restore, "backup_files", lambda data, passphrase: iter(()))

    transfer.import_manager(exported, "a-long-export-passphrase", replace=True)

    stored = BackupPlan.objects.get(pk=plan.pk)
    assert (stored.keep, stored.keep_remote) == (5, 5)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "change", [{"keep": 2}, {"keep_remote": 0}, {"keep": 2, "keep_remote": 3}]
)
def test_keeping_fewer_needs_the_account_password(api, make_plan, change):
    plan = make_plan(keep=3, keep_remote=1)

    asked = api.patch(url(plan), change, format="json")
    wrong = api.patch(url(plan), {**change, "account_password": "wrong"}, format="json")
    kept = BackupPlan.objects.get(pk=plan.pk)

    assert asked.status_code == 400
    assert asked.json()["error"]["fields"] == {"account_password": ["required"]}
    assert wrong.json()["error"]["code"] == "invalid_password"
    assert (kept.keep, kept.keep_remote) == (3, 1)
    assert [entry.error_code for entry in logged("plan.update")] == ["invalid_password"]


@pytest.mark.django_db
def test_keeping_fewer_with_the_password_is_saved_and_logged(api, admin, make_plan):
    plan = make_plan(keep=3, keep_remote=1)

    response = api.patch(
        url(plan),
        {"keep": 1, "keep_remote": 0, "account_password": PASSWORD},
        format="json",
    )

    assert response.status_code == 200
    assert (response.json()["keep"], response.json()["keep_remote"]) == (1, 0)
    [entry] = logged("plan.update")
    assert (entry.status, entry.actor) == ("succeeded", admin)
    assert entry.data == {"fields": ["keep", "keep_remote"]}


@pytest.mark.django_db
def test_keeping_more_or_the_same_needs_no_password(api, make_plan):
    plan = make_plan(keep=3, keep_remote=1)

    more = api.patch(url(plan), {"keep": 5, "keep_remote": 2}, format="json")
    same = api.patch(url(plan), {"keep": 5, "keep_remote": 2}, format="json")

    assert more.status_code == same.status_code == 200
    assert (more.json()["keep"], more.json()["keep_remote"]) == (5, 2)


@pytest.mark.django_db
def test_a_collect_plan_keeps_no_copy_on_the_server_and_asks_nothing_for_it(
    api, make_plan
):
    plan = make_plan(name="dumps", kind="collect", paths=["/var/backups"], keep=3)

    response = api.patch(url(plan), {"keep_remote": 0, "keep": 4}, format="json")

    assert response.status_code == 200
    assert (response.json()["keep"], response.json()["keep_remote"]) == (4, 0)


@pytest.mark.django_db(transaction=True)
def test_only_a_confirmed_change_lets_a_run_delete_older_backups(api, make_plan, ran):
    plan = make_plan(keep=3)
    for _ in range(3):
        ran(plan)

    api.patch(url(plan), {"keep": 1}, format="json")
    ran(plan)
    before = BackupFileRepository().alive_for_plan(plan.pk).count()
    api.patch(url(plan), {"keep": 1, "account_password": PASSWORD}, format="json")
    ran(plan)

    assert before == 3
    assert BackupFileRepository().alive_for_plan(plan.pk).count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize("name", ["Nightly", "nightly!", "nightly.", "NIGHTLY "])
def test_a_name_that_would_share_the_plans_files_on_the_server_is_taken(
    api, server, make_plan, name
):
    make_plan(name="nightly")
    other = make_plan(name="weekly")

    added = api.post(
        PLANS,
        {"server": str(server.pk), "name": name, "kind": "dbs"},
        format="json",
    )
    renamed = api.patch(url(other), {"name": name}, format="json")

    assert added.json()["error"]["fields"] == {"name": ["name_taken"]}
    assert renamed.json()["error"]["fields"] == {"name": ["name_taken"]}


@pytest.mark.django_db
def test_a_name_without_letters_or_digits_never_clashes(api, server, make_plan):
    make_plan(name="!!!")

    added = api.post(
        PLANS,
        {"server": str(server.pk), "name": "???", "kind": "dbs"},
        format="json",
    )

    assert added.status_code == 201
