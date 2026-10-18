from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient

from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.backups.models import BackupPlan
from dbs.manager.backups.repositories import BackupPlanRepository
from dbs.manager.backups.services import backup_schedule_service
from dbs.manager.backups.timing import next_on_grid
from dbs.manager.permissions import Role
from dbs.models import AuditEvent
from tests.manager.support import PASSWORD

PLANS = "/api/backups/plans/"
BERLIN = ZoneInfo("Europe/Berlin")
DAY = timedelta(days=1)


def moment(text):
    return parse_datetime(text)


def stored(plan):
    return BackupPlan.objects.get(pk=plan.pk)


def later(days=2, hour=2):
    found = timezone.now().astimezone(BERLIN) + timedelta(days=days)
    return found.replace(hour=hour, minute=0, second=0, microsecond=0)


def test_a_daily_run_keeps_its_wall_clock_time_across_both_daylight_saving_changes():
    spring = datetime(2026, 3, 27, 2, 0, tzinfo=BERLIN)
    autumn = datetime(2026, 10, 23, 2, 0, tzinfo=BERLIN)

    after_spring = next_on_grid(spring, 1440, "Europe/Berlin", spring + 3 * DAY)
    after_autumn = next_on_grid(autumn, 1440, "Europe/Berlin", autumn + 3 * DAY)

    assert after_spring.astimezone(BERLIN).hour == 2
    assert after_spring == datetime(2026, 3, 31, 0, 0, tzinfo=dt_timezone.utc)
    assert after_autumn.astimezone(BERLIN).hour == 2
    assert after_autumn == datetime(2026, 10, 27, 1, 0, tzinfo=dt_timezone.utc)


def test_a_weekly_run_keeps_its_weekday_and_hours_count_in_plain_time():
    start = datetime(2026, 3, 23, 6, 30, tzinfo=BERLIN)
    hourly_start = datetime(2026, 3, 29, 0, 30, tzinfo=dt_timezone.utc)

    weekly = next_on_grid(start, 10080, "Europe/Berlin", start + timedelta(days=8))
    hourly = next_on_grid(hourly_start, 60, "Europe/Berlin", hourly_start + timedelta(hours=3))

    assert weekly.astimezone(BERLIN).replace(tzinfo=None) == datetime(2026, 4, 6, 6, 30)
    assert hourly == hourly_start + timedelta(hours=4)


@pytest.mark.django_db
def test_a_plan_with_a_first_run_starts_then_and_keeps_that_beat(api, application):
    first = later()

    created = api.post(
        PLANS,
        {
            "application": str(application.pk),
            "name": "nightly",
            "kind": "dbs",
            "interval_minutes": 1440,
            "anchor_at": first.isoformat(),
            "time_zone": "Europe/Berlin",
        },
        format="json",
    ).json()

    assert moment(created["next_run_at"]) == first
    assert moment(created["anchor_at"]) == first
    assert created["time_zone"] == "Europe/Berlin"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "fields, field, code",
    [
        ({"anchor_at": "2020-01-01T00:00:00Z"}, "anchor_at", "invalid_moment"),
        ({"anchor_at": "2099-01-01T00:00:00Z"}, "anchor_at", "invalid_moment"),
        ({"time_zone": "Mars/Olympus"}, "time_zone", "invalid_time_zone"),
        ({"time_zone": "../../etc/passwd"}, "time_zone", "invalid_time_zone"),
    ],
)
def test_a_first_run_must_be_ahead_within_a_year_in_a_known_time_zone(
    api, application, fields, field, code
):
    response = api.post(
        PLANS,
        {
            "application": str(application.pk),
            "name": "nightly",
            "kind": "dbs",
            "interval_minutes": 1440,
            **fields,
        },
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {field: [code]}
    assert not BackupPlan.objects.exists()


@pytest.mark.django_db
def test_rescheduling_moves_the_next_run_and_the_beat_after_it(
    api, make_plan, run_jobs, host
):
    plan = make_plan()
    chosen = later(days=3, hour=4)

    response = api.post(
        f"{PLANS}{plan.pk}/reschedule/", {"next_run_at": chosen.isoformat()}, format="json"
    )
    BackupPlanRepository().update(
        stored(plan),
        next_run_at=chosen - 3 * DAY,
        anchor_at=chosen - 3 * DAY,
    )
    with run_jobs():
        backup_schedule_service.dispatch_due_plans()

    assert response.status_code == 200
    assert moment(response.json()["next_run_at"]) == chosen
    assert stored(plan).next_run_at.astimezone(BERLIN).hour == 4
    [entry] = AuditEvent.objects.filter(action="plan.reschedule")
    assert moment(entry.data["next_run_at"]) == chosen


@pytest.mark.django_db
def test_a_reschedule_into_the_past_or_of_a_manual_plan_is_refused(api, make_plan):
    plan = make_plan()
    manual = make_plan(name="manual", interval_minutes=None)

    past = api.post(
        f"{PLANS}{plan.pk}/reschedule/",
        {"next_run_at": "2020-01-01T00:00:00Z"},
        format="json",
    )
    by_hand = api.post(
        f"{PLANS}{manual.pk}/reschedule/",
        {"next_run_at": later().isoformat()},
        format="json",
    )

    assert past.json()["error"]["fields"] == {"next_run_at": ["invalid_moment"]}
    assert by_hand.json()["error"]["fields"] == {"interval_minutes": ["manual_plan"]}
    assert not AuditEvent.objects.filter(action="plan.reschedule").exists()


@pytest.mark.django_db
def test_a_paused_plan_never_runs_and_resumes_on_its_beat_without_catching_up(
    api, make_plan, run_jobs, host
):
    plan = make_plan(interval_minutes=60)
    beat = stored(plan).anchor_at

    paused = api.post(f"{PLANS}{plan.pk}/pause/").json()
    BackupPlanRepository().update(stored(plan), anchor_at=beat - 5 * DAY)
    with run_jobs():
        backup_schedule_service.dispatch_due_plans()
    resumed = api.post(f"{PLANS}{plan.pk}/resume/").json()

    assert (paused["enabled"], paused["next_run_at"]) == (False, None)
    assert host.takes == []
    following = moment(resumed["next_run_at"])
    assert resumed["enabled"] is True
    assert timezone.now() < following <= timezone.now() + timedelta(hours=1)
    assert (following - (beat - 5 * DAY)) % timedelta(hours=1) == timedelta(0)
    assert [entry.action for entry in AuditEvent.objects.filter(action__startswith="plan.p")] == [
        "plan.pause"
    ]
    assert AuditEvent.objects.filter(action="plan.resume").count() == 1


@pytest.mark.django_db
def test_a_new_interval_starts_a_new_beat_but_a_new_time_zone_keeps_it(api, make_plan):
    plan = make_plan(time_zone="UTC")
    anchor = stored(plan).anchor_at

    zoned = api.patch(
        f"{PLANS}{plan.pk}/", {"time_zone": "Europe/Berlin"}, format="json"
    ).json()
    hourly = api.patch(
        f"{PLANS}{plan.pk}/", {"interval_minutes": 60}, format="json"
    ).json()

    assert moment(zoned["anchor_at"]) == anchor
    assert moment(hourly["anchor_at"]) != anchor
    assert timezone.now() < moment(hourly["next_run_at"]) <= timezone.now() + timedelta(hours=1)


@pytest.mark.django_db
def test_an_operator_runs_plans_but_may_not_pause_or_move_them(application, make_plan):
    plan = make_plan()
    operator = UserRepository().create(
        username="omar", password=PASSWORD, role=Role.OPERATOR
    )
    client = APIClient()
    client.force_login(operator)

    paused = client.post(f"{PLANS}{plan.pk}/pause/")
    moved = client.post(
        f"{PLANS}{plan.pk}/reschedule/",
        {"next_run_at": later().isoformat()},
        format="json",
    )

    assert [paused.status_code, moved.status_code] == [403, 403]
    assert stored(plan).enabled is True
