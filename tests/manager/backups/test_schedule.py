from __future__ import annotations

import os
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from uuid import uuid4

import pytest
from django.utils import timezone

from dbs import audit
from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.activity.services import ActivityService
from dbs.manager.backups.locks import TakeLock
from dbs.manager.backups.models import BackupFile, BackupPlan
from dbs.manager.backups.repositories import BackupFileRepository, BackupPlanRepository
from dbs.manager.backups.services import (
    BackupPlanService,
    BackupRunService,
    BackupService,
    backup_schedule_service,
)
from dbs.manager.backups.services.backup_schedule_service import following
from dbs.manager.backups.storage import BackupStorage
from dbs.manager.scheduler import TASKS
from dbs.manager.servers.services import ServerService
from tests.manager.support import backdated

DAY = timedelta(days=1)
HOUR = timedelta(hours=1)


def runs():
    return list(ActivityRepository().filtered(action="backup.run"))


def stored(plan) -> BackupPlan:
    return BackupPlanRepository().all_including_deleted().get(pk=plan.pk)


def due(plan, ago: timedelta = timedelta(minutes=1)) -> datetime:
    moment = timezone.now() - ago
    BackupPlanRepository().update(stored(plan), next_run_at=moment)
    return moment


def dispatch(run_jobs) -> None:
    with run_jobs():
        backup_schedule_service.dispatch_due_plans()


@pytest.mark.django_db
def test_a_due_plan_is_run_by_no_one_and_scheduled_one_interval_on(
    server, host, make_plan, run_jobs
):
    plan = make_plan()
    was_due = due(plan)

    dispatch(run_jobs)

    [job] = runs()
    assert (job.status, job.subject, job.target_name) == (
        audit.SUCCEEDED,
        str(server.pk),
        "django-dbs",
    )
    assert (job.actor, job.remote_addr) == (None, "")
    assert job.data["plan"] == str(plan.pk)
    backup = BackupFileRepository().get(job.data["backup"])
    assert (backup.plan, backup.created_by) == (plan, None)
    assert stored(plan).next_run_at == was_due + DAY
    assert stored(plan).last_status == "succeeded"
    assert len(host.takes) == 1


@pytest.mark.django_db
def test_a_plan_that_is_not_due_yet_waits(host, make_plan, run_jobs):
    plan = make_plan()
    scheduled = stored(plan).next_run_at

    dispatch(run_jobs)

    assert runs() == []
    assert stored(plan).next_run_at == scheduled


@pytest.mark.django_db
def test_disabled_manual_and_deleted_plans_and_deleted_servers_are_never_run(
    admin, server, host, make_plan, run_jobs
):
    disabled = make_plan(name="disabled", enabled=False)
    manual = make_plan(name="manual", interval_minutes=None)
    deleted = make_plan(name="deleted")
    BackupPlanService(admin).delete(deleted.pk)
    for plan in (disabled, manual, deleted):
        due(plan)
    other = ServerService(admin).create(
        name="web-2",
        host="10.0.0.6",
        username="deploy",
        auth_method="password",
        password="ssh-password",
        host_key=server.host_key,
    )
    orphan = make_plan(server=other.pk, name="orphan")
    due(orphan)
    ServerService(admin).delete(other.pk)

    dispatch(run_jobs)

    assert runs() == []
    assert host.takes == []


@pytest.mark.django_db
def test_a_plan_that_missed_several_runs_runs_once_at_its_usual_time(
    host, make_plan, run_jobs
):
    plan = make_plan()
    was_due = due(plan, ago=5 * DAY + timedelta(hours=3))

    dispatch(run_jobs)
    dispatch(run_jobs)

    assert len(runs()) == 1
    assert stored(plan).next_run_at == was_due + 6 * DAY
    assert timezone.now() < stored(plan).next_run_at <= timezone.now() + DAY


def test_the_next_run_is_the_first_on_the_plans_beat_after_now():
    start = datetime(2026, 10, 1, 3, 0, tzinfo=dt_timezone.utc)
    hour = timedelta(hours=1)

    assert following(start, hour, start) == start + hour
    assert following(start, hour, start + timedelta(minutes=59)) == start + hour
    assert following(start, hour, start + hour) == start + 2 * hour
    assert following(start, DAY, start + 3 * DAY + hour) == start + 4 * DAY


@pytest.mark.django_db
def test_a_scheduled_run_that_finds_the_server_busy_fails_at_once(
    admin, server, host, make_plan, run_jobs, django_capture_on_commit_callbacks
):
    plan = make_plan()
    was_due = due(plan)
    with django_capture_on_commit_callbacks():
        take = BackupService(admin).take(server.pk)

    dispatch(run_jobs)

    [job] = runs()
    assert (job.status, job.error_code) == (audit.FAILED, "backup_running")
    assert job.data == {"plan": str(plan.pk)}
    assert job.started_at is None and job.finished_at is not None
    assert host.takes == []
    plan = stored(plan)
    assert (plan.last_status, plan.last_error_code) == ("failed", "backup_running")
    assert plan.last_run_at == job.finished_at
    assert plan.next_run_at == was_due + DAY
    assert TakeLock().hold(server.pk, take.pk)


@pytest.mark.django_db
def test_a_scheduled_run_the_broker_refuses_fails_and_lets_the_server_go(
    monkeypatch, server, host, make_plan, run_jobs
):
    def unreachable(*args):
        raise RuntimeError("cannot schedule new futures after shutdown")

    monkeypatch.setattr("dbs.manager.runner.JobRunner.submit", unreachable)
    due(make_plan())

    dispatch(run_jobs)

    [job] = runs()
    assert (job.status, job.error_code) == (audit.FAILED, "unexpected")
    assert TakeLock().acquire(server.pk, uuid4())


def deleted(admin, backup: BackupFile, ago: timedelta) -> BackupFile:
    BackupService(admin).delete(backup.pk)
    row = BackupFileRepository().find_including_deleted(backup.pk)
    return BackupFileRepository().update(row, deleted_at=timezone.now() - ago)


@pytest.mark.django_db
def test_files_deleted_longer_ago_than_the_grace_period_leave_the_disk(
    api, admin, server, storage, taken, run_jobs
):
    expired = deleted(admin, taken(), ago=8 * DAY)
    recent = deleted(admin, taken(), ago=6 * DAY)
    kept = taken()

    with run_jobs():
        backup_schedule_service.remove_expired_files()

    files = BackupStorage()
    assert not files.exists(expired.storage_path)
    assert (
        BackupFileRepository().find_including_deleted(expired.pk).removed_at is not None
    )
    for row in (recent, kept):
        assert files.exists(row.storage_path)
        assert BackupFileRepository().find_including_deleted(row.pk).removed_at is None
    [entry] = ActivityRepository().filtered(action="backup.expire")
    assert entry.data == {"removed": 1}
    assert (entry.subject, entry.target_name, entry.actor, entry.remote_addr) == (
        "",
        "",
        None,
        "",
    )
    undo = api.post(f"/api/backups/{expired.pk}/undo-delete/")
    assert undo.status_code == 404
    assert undo.json()["error"]["code"] == "not_found"
    assert api.post(f"/api/backups/{recent.pk}/undo-delete/").status_code == 200


@pytest.mark.django_db
def test_a_file_is_removed_once_and_a_quiet_day_writes_nothing(
    admin, settings, taken, run_jobs
):
    settings.BACKUP_GRACE_DAYS = 2
    deleted(admin, taken(), ago=3 * DAY)
    deleted(admin, taken(), ago=3 * DAY)

    with run_jobs():
        backup_schedule_service.remove_expired_files()
    with run_jobs():
        backup_schedule_service.remove_expired_files()

    [entry] = ActivityRepository().filtered(action="backup.expire")
    assert entry.data == {"removed": 2}


@pytest.mark.django_db
def test_what_an_upload_that_never_finished_left_leaves_the_disk_after_a_day(run_jobs):
    uploads = BackupStorage().uploads_directory()
    now = timezone.now()
    for name, ago in (
        ("killed.upload", DAY + timedelta(minutes=1)),
        ("arriving.upload", HOUR),
    ):
        path = uploads / name
        path.write_bytes(b"plaintext")
        os.utime(path, ((now - ago).timestamp(), (now - ago).timestamp()))

    with run_jobs():
        backup_schedule_service.remove_expired_files()

    assert [path.name for path in uploads.iterdir()] == ["arriving.upload"]
    assert list(ActivityRepository().filtered(action="backup.expire")) == []


def job_entry(admin, server, *, queued_ago: timedelta, started_ago: timedelta | None):
    activity = ActivityService(admin)
    job = activity.queue("backup.take", server=server, target=server.name)
    if started_ago is not None:
        job = ActivityService(None).start(job.pk)
        job = backdated(job, started_at=timezone.now() - started_ago)
    return backdated(job, created_at=timezone.now() - queued_ago)


@pytest.mark.django_db
def test_jobs_no_worker_will_finish_are_failed_as_interrupted(
    admin, server, host, settings, run_jobs
):
    settings.BACKUP_TASK_TIME_LIMIT = 6 * 60 * 60
    never_started = job_entry(
        admin, server, queued_ago=timedelta(hours=8), started_ago=None
    )
    died = job_entry(
        admin, server, queued_ago=timedelta(hours=9), started_ago=timedelta(hours=8)
    )
    waiting = job_entry(admin, server, queued_ago=timedelta(hours=6), started_ago=None)
    running = job_entry(
        admin, server, queued_ago=timedelta(hours=9), started_ago=timedelta(hours=6)
    )

    with run_jobs():
        backup_schedule_service.BackupScheduleService().sweep_stale_jobs()

    def now(entry):
        return ActivityRepository().get(entry.pk)

    for entry in (never_started, died):
        assert (now(entry).status, now(entry).error_code) == (
            audit.FAILED,
            "interrupted",
        )
        assert now(entry).finished_at is not None
    assert now(waiting).status == audit.QUEUED
    assert now(running).status == audit.RUNNING

    BackupRunService().take(never_started.pk)
    assert host.takes == []
    assert now(never_started).error_code == "interrupted"


@pytest.mark.django_db
def test_a_finished_job_is_never_swept(admin, server, run_jobs, taken):
    taken()
    [finished] = ActivityRepository().filtered(action="backup.take")
    backdated(finished, created_at=timezone.now() - 30 * DAY)

    with run_jobs():
        backup_schedule_service.BackupScheduleService().sweep_stale_jobs()

    again = ActivityRepository().get(finished.pk)
    assert (again.status, again.error_code) == (audit.SUCCEEDED, "")


def test_the_scheduler_runs_each_backup_task_on_its_schedule():
    assert TASKS["dispatch_due_plans"] == (
        timedelta(minutes=1),
        "dbs.manager.backups.services.backup_schedule_service.dispatch_due_plans",
    )
    assert TASKS["remove_expired_files"][0] == DAY
    assert TASKS["sweep_stale_jobs"][0] == timedelta(minutes=15)
