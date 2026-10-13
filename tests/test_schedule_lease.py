"""The scheduler's short lease: renewed while a backup runs, recovered when a run dies."""

import os
import time
from datetime import timedelta

import pytest
from django.utils import timezone

from dbs import audit, jobs, leases, schedule_runner
from dbs.models import AuditEvent, BackupSchedule, Lease


@pytest.fixture
def backup_dir(tmp_path, settings):
    directory = tmp_path / "backups"
    settings.DBS_BACKUP_DIR = str(directory)
    return directory


@pytest.fixture
def watched(monkeypatch):
    from dbs.engine import backup

    seen = []
    real = backup.write_backup

    def write_backup(*args, **kwargs):
        seen.append(
            {
                "events": list(AuditEvent.objects.values("action", "status", "target_name")),
                "schedule": BackupSchedule.objects.values("last_status", "next_run_at").get(),
                "job_leases": list(
                    Lease.objects.filter(name__startswith=jobs.JOB_LEASE_PREFIX).values_list(
                        "name", flat=True
                    )
                ),
                "runner": leases.holder(jobs.RUNNER_LEASE),
                "second": schedule_runner.run_due(force=True),
            }
        )
        return real(*args, **kwargs)

    monkeypatch.setattr(backup, "write_backup", write_backup)
    return seen


def dead_run(status, now):
    event = audit.record("backup.create", target="lost.dbs", status=audit.RUNNING)
    expired = now - timedelta(seconds=1)
    Lease.objects.create(name=jobs.job_lease(event.pk), owner="dead", expires_at=expired)
    Lease.objects.create(name=jobs.RUNNER_LEASE, owner="dead", expires_at=expired)
    BackupSchedule.objects.create(
        enabled=True, interval="6h", last_status=status, next_run_at=now - timedelta(hours=1)
    )
    return event


@pytest.mark.django_db
def test_a_run_is_recorded_as_running_and_holds_its_leases_until_it_ends(backup_dir, watched):
    BackupSchedule.objects.create(enabled=True, interval="6h")
    now = timezone.now()

    output = schedule_runner.run_due(now=now)

    during = watched[0]
    assert during["events"] == [
        {"action": "backup.create", "status": "running", "target_name": os.path.basename(output)}
    ]
    assert during["schedule"] == {"last_status": "running", "next_run_at": None}
    assert len(during["job_leases"]) == 1
    assert during["runner"] is not None
    assert during["second"] is None
    event = AuditEvent.objects.get(action="backup.create")
    assert event.status == audit.SUCCEEDED and event.finished_at is not None
    schedule = BackupSchedule.load()
    assert schedule.last_status == "succeeded"
    assert schedule.next_run_at == now + timedelta(hours=6)
    assert not Lease.objects.filter(name__startswith=jobs.JOB_LEASE_PREFIX).exists()
    assert leases.holder(jobs.RUNNER_LEASE) is None


@pytest.mark.django_db
def test_a_failed_run_is_closed_and_waits_for_the_next_interval(backup_dir, monkeypatch):
    from dbs.engine import backup
    from dbs.exceptions import DBSError

    def explode(*args, **kwargs):
        raise DBSError("disk full")

    monkeypatch.setattr(backup, "write_backup", explode)
    BackupSchedule.objects.create(enabled=True, interval="6h")
    now = timezone.now()

    with pytest.raises(DBSError):
        schedule_runner.run_due(now=now)

    event = AuditEvent.objects.get(action="backup.create")
    assert (event.status, event.error_code, event.detail) == ("failed", "DBSError", "disk full")
    schedule = BackupSchedule.load()
    assert (schedule.last_status, schedule.last_error) == ("failed", "disk full")
    assert schedule.next_run_at == now + timedelta(hours=6)
    assert [path.stat().st_size for path in backup_dir.iterdir()] == []


@pytest.mark.django_db
def test_a_killed_run_is_taken_again_at_the_next_tick(backup_dir):
    now = timezone.now()
    lost = dead_run("running", now)

    output = schedule_runner.run_due(now=now)

    assert output is not None and os.path.isfile(output)
    lost.refresh_from_db()
    assert (lost.status, lost.error_code) == (audit.FAILED, audit.INTERRUPTED)
    schedule = BackupSchedule.load()
    assert schedule.last_status == "succeeded"
    assert schedule.next_run_at == now + timedelta(hours=6)


@pytest.mark.django_db
def test_a_retry_that_is_killed_too_waits_for_the_next_interval(backup_dir):
    now = timezone.now()
    lost = dead_run("retrying", now)

    assert schedule_runner.run_due(now=now) is None

    lost.refresh_from_db()
    assert lost.status == audit.FAILED
    schedule = BackupSchedule.load()
    assert schedule.last_status == "failed"
    assert "Two scheduled backups" in schedule.last_error
    assert schedule.next_run_at == now + timedelta(hours=6)
    assert not backup_dir.exists()


@pytest.mark.django_db
def test_recovery_only_touches_jobs_whose_lease_expired():
    now = timezone.now()
    dead = audit.record("backup.restore", status=audit.RUNNING)
    alive = audit.record("backup.create", status=audit.RUNNING)
    elsewhere = audit.record("backup.take", status=audit.RUNNING)
    Lease.objects.create(
        name=jobs.job_lease(dead.pk), owner="dead", expires_at=now - timedelta(seconds=1)
    )
    Lease.objects.create(
        name=jobs.job_lease(alive.pk), owner="alive", expires_at=now + timedelta(minutes=1)
    )

    assert jobs.recover(now) == 1

    statuses = dict(AuditEvent.objects.values_list("pk", "status"))
    assert statuses == {dead.pk: "failed", alive.pk: "running", elsewhere.pk: "running"}
    assert list(Lease.objects.values_list("name", flat=True)) == [jobs.job_lease(alive.pk)]


@pytest.mark.django_db
def test_one_runner_at_a_time():
    first = jobs.Runner().take()
    try:
        with pytest.raises(jobs.Busy):
            jobs.Runner().take()
    finally:
        first.release()

    jobs.Runner().take().release()


@pytest.mark.django_db
def test_each_tick_clears_leftovers_older_than_an_hour(backup_dir):
    backup_dir.mkdir()
    leftover = backup_dir / ".backup-20260101-000000Z.dbs.ab12cd34"
    leftover.write_bytes(b"partial")
    fresh = backup_dir / ".backup-20260101-000001Z.dbs.ab12cd35"
    fresh.write_bytes(b"partial")
    hours_ago = time.time() - 7200
    os.utime(leftover, (hours_ago, hours_ago))

    schedule_runner.tick()

    assert not leftover.exists() and fresh.exists()


@pytest.mark.django_db(transaction=True)
def test_the_heartbeat_keeps_a_short_lease_for_as_long_as_the_work_runs():
    assert leases.acquire("job", "worker", 2)

    with leases.Heartbeat(["job"], "worker", 2, 0.1) as beating:
        time.sleep(3)

    assert not beating.lost.is_set()
    assert leases.holder("job").owner == "worker"
    assert not leases.acquire("job", "intruder", 2)
    time.sleep(2.5)
    assert leases.acquire("job", "intruder", 2)


@pytest.mark.django_db
def test_a_heartbeat_notices_a_lease_it_no_longer_holds():
    leases.acquire("job", "worker", 60)
    leases.acquire("other", "worker", 60)
    Lease.objects.filter(name="job").update(owner="someone-else")

    beat = leases.Heartbeat(["job", "other"], "worker", 60, 30)
    beat.beat()

    assert beat.lost.is_set()
    assert leases.holder("other").owner == "worker"
