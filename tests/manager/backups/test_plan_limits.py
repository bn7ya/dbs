from __future__ import annotations

import pytest

from dbs.manager.applications.models import Application
from dbs.manager.backups import limits
from dbs.manager.backups.models import BackupPlan
from dbs.manager.backups.repositories import BackupFileRepository, BackupPlanRepository
from dbs.manager.conf import backup_keep_max
from dbs.manager.dashboard.services import DashboardService
from dbs.retention import keep_limit
from tests.manager.servers.support import PASSWORD

PLANS = "/api/backups/plans/"
LIMITS = "/api/backups/plans/limits/"


def url(plan) -> str:
    return f"{PLANS}{plan.pk}/"


def body(application, **fields):
    return {"application": str(application.pk), "name": "nightly", "kind": "dbs", **fields}


def reporting(application, max_backups):
    Application.objects.filter(pk=application.pk).update(
        last_check_report={"dbs_version": "0.9.0", "max_backups": max_backups}
    )


def test_the_manager_keeps_five_until_its_environment_says_otherwise():
    assert backup_keep_max() == 5


@pytest.mark.parametrize(
    ("configured", "kept"),
    [(None, 5), ("", 5), ("1", 1), ("40", 40), ("10000", 10000), ("0", 1), ("99999", 10000), ("x", 5)],
)
def test_the_environment_variable_is_read_within_one_and_ten_thousand(configured, kept):
    assert keep_limit(configured or None) == kept


@pytest.mark.django_db
def test_the_limits_of_a_plan_are_those_of_the_manager_and_the_server(api, application):
    limits_now = api.get(LIMITS, {"application": str(application.pk)})

    assert limits_now.status_code == 200
    assert limits_now.json() == {
        "keep": {"min": 1, "max": 5},
        "keep_remote": {"min": 0, "max": 5},
    }


@pytest.mark.django_db
def test_the_limits_follow_the_manager_and_what_the_server_reported(
    api, application, settings
):
    settings.BACKUP_KEEP_MAX = 60
    reporting(application, 30)

    limits_now = api.get(LIMITS, {"application": str(application.pk)}).json()

    assert (limits_now["keep"]["max"], limits_now["keep_remote"]["max"]) == (60, 30)
    assert DashboardService(None).about()["max_backups"] == 60


@pytest.mark.django_db
def test_the_limits_need_an_application_and_a_signed_in_account(api, anonymous, application):
    assert api.get(LIMITS).status_code == 400
    assert anonymous.get(LIMITS, {"application": str(application.pk)}).status_code in (401, 403)


@pytest.mark.django_db
@pytest.mark.parametrize("reported", [None, 0, 10001, "many", True])
def test_a_server_that_reports_no_usable_limit_keeps_five(application, reported):
    reporting(application, reported)
    application.refresh_from_db()

    assert limits.keep_remote_max(application) == 5


@pytest.mark.django_db
def test_a_plan_keeps_here_up_to_the_managers_limit(api, application, settings):
    settings.BACKUP_KEEP_MAX = 12

    kept = api.post(PLANS, body(application, keep=12), format="json")
    beyond = api.post(PLANS, body(application, name="weekly", keep=13), format="json")

    assert kept.status_code == 201 and kept.json()["keep"] == 12
    assert beyond.json()["error"]["fields"] == {"keep": ["max_value"]}


@pytest.mark.django_db
def test_a_plan_keeps_on_the_server_up_to_what_the_server_allows(api, application):
    reporting(application, 25)

    kept = api.post(PLANS, body(application, keep_remote=25), format="json")
    beyond = api.post(PLANS, body(application, name="weekly", keep_remote=26), format="json")

    assert kept.status_code == 201 and kept.json()["keep_remote"] == 25
    assert beyond.json()["error"]["fields"] == {"keep_remote": ["max_value"]}


@pytest.mark.django_db
def test_no_plan_keeps_more_than_ten_thousand(api, application, settings):
    settings.BACKUP_KEEP_MAX = 10000
    reporting(application, 10000)

    most = api.post(PLANS, body(application, keep=10000, keep_remote=10000), format="json")
    beyond = api.post(
        PLANS, body(application, name="weekly", keep=10001, keep_remote=10001), format="json"
    )

    assert most.status_code == 201
    assert beyond.json()["error"]["fields"] == {
        "keep": ["max_value"],
        "keep_remote": ["max_value"],
    }


@pytest.mark.django_db
def test_a_plan_above_a_lowered_limit_can_still_be_changed_and_lowered(
    api, make_plan, settings
):
    settings.BACKUP_KEEP_MAX = 20
    plan = make_plan(keep=20, keep_remote=0)
    settings.BACKUP_KEEP_MAX = 5

    renamed = api.patch(url(plan), {"name": "renamed", "keep": 20}, format="json")
    lowered = api.patch(url(plan), {"keep": 8, "account_password": PASSWORD}, format="json")
    raised = api.patch(url(plan), {"keep": 9}, format="json")

    assert renamed.status_code == 200
    assert lowered.status_code == 200 and lowered.json()["keep"] == 8
    assert raised.json()["error"]["fields"] == {"keep": ["max_value"]}


@pytest.mark.django_db
def test_a_run_keeps_as_many_as_the_limit_raised_since_allows(
    application, host, make_plan, ran, settings
):
    settings.BACKUP_KEEP_MAX = 7
    plan = make_plan(keep=7, keep_remote=0)

    for _ in range(9):
        ran(plan)

    assert BackupFileRepository().alive_for_plan(plan.pk).count() == 7


@pytest.mark.django_db
def test_backups_taken_by_hand_are_kept_up_to_the_managers_limit(
    application, host, taken, settings
):
    settings.BACKUP_KEEP_MAX = 3

    for _ in range(5):
        taken()

    assert len(BackupFileRepository().good_backups(application.pk, None)) == 3


@pytest.mark.django_db
def test_an_import_brings_plans_within_the_limits_of_this_manager(
    make_plan, application, settings
):
    settings.BACKUP_KEEP_MAX = 8
    reporting(application, 6)
    plan = make_plan(keep=5, keep_remote=0)
    BackupPlan.objects.filter(pk=plan.pk).update(keep=30, keep_remote=9)

    BackupPlanRepository().keep_within_limits()

    stored = BackupPlan.objects.get(pk=plan.pk)
    assert (stored.keep, stored.keep_remote) == (8, 6)
