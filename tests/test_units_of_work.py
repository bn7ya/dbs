"""What must be true together is written in one transaction, or not at all."""

from datetime import timedelta

import pytest
from django.contrib import admin
from django.db import DatabaseError
from django.utils import timezone

from dbs import audit, checkpoints, job_process, jobs, leases
from dbs.admin import KnownLocationAdmin
from dbs.engine import schema
from dbs.models import AnomalyEvent, AuditEvent, KnownLocation, Lease, Lockout
from dbs.security import guard


class Broken(DatabaseError):
    pass


def failing(*args, **kwargs):
    raise Broken("the database went away")


def after(real):
    def run(*args, **kwargs):
        real(*args, **kwargs)
        raise Broken("the database went away")

    return run


def running_job(owner="child"):
    return jobs.Job.begin(jobs.BACKUP, target="shop.dbs", data={}, owner=owner)


@pytest.fixture
def superuser_request(rf, admin_user):
    request = rf.post("/admin/")
    request.user = admin_user
    return request


@pytest.mark.django_db
def test_a_job_starts_with_its_audit_row_and_its_lease_or_with_neither(monkeypatch):
    monkeypatch.setattr(leases, "acquire", failing)

    with pytest.raises(Broken):
        running_job()

    assert not AuditEvent.objects.exists()


@pytest.mark.django_db
def test_a_job_ends_with_its_last_status_and_without_its_lease_or_stays_as_it_was(monkeypatch):
    job = running_job()
    monkeypatch.setattr(leases, "drop", failing)

    with pytest.raises(Broken):
        job.end()

    assert AuditEvent.objects.get(pk=job.event_id).status == audit.RUNNING
    assert leases.holder(job.lease).owner == "child"


@pytest.mark.django_db
def test_a_job_that_ends_is_finished_and_holds_no_lease():
    job = running_job()

    job.end()

    assert AuditEvent.objects.get(pk=job.event_id).status == audit.SUCCEEDED
    assert not Lease.objects.filter(name=job.lease).exists()


@pytest.mark.django_db
def test_stopped_jobs_are_interrupted_and_their_leases_dropped_together(monkeypatch):
    event = audit.record(jobs.BACKUP, target="lost.dbs", status=audit.RUNNING)
    lease = jobs.job_lease(event.pk)
    Lease.objects.create(
        name=lease, owner="dead", expires_at=timezone.now() - timedelta(seconds=1)
    )
    monkeypatch.setattr(audit, "interrupt", after(audit.interrupt))

    with pytest.raises(Broken):
        jobs.recover()

    assert AuditEvent.objects.get(pk=event.pk).status == audit.RUNNING
    assert Lease.objects.filter(name=lease).exists()


@pytest.mark.django_db
def test_a_killed_job_is_settled_whole_or_not_at_all(monkeypatch):
    job = running_job()
    leases.acquire(jobs.RUNNER_LEASE, "child", 60)
    monkeypatch.setattr(leases, "release", failing)

    with pytest.raises(Broken):
        job_process.settle("child", 137, "killed")

    assert AuditEvent.objects.get(pk=job.event_id).status == audit.RUNNING
    assert Lease.objects.filter(name=job.lease, owner="child").exists()


@pytest.mark.django_db
def test_a_killed_job_is_failed_and_gives_up_every_lease():
    job = running_job()
    leases.acquire(jobs.RUNNER_LEASE, "child", 60)

    job_process.settle("child", 137, "killed")

    settled = AuditEvent.objects.get(pk=job.event_id)
    assert (settled.status, settled.error_code) == (audit.FAILED, job_process.KILLED)
    assert not Lease.objects.filter(name=job.lease).exists()
    assert leases.holder(jobs.RUNNER_LEASE) is None


@pytest.mark.django_db
def test_a_lockout_is_written_with_the_anomaly_behind_it(superuser_request, monkeypatch):
    monkeypatch.setattr(Lockout.objects, "get_or_create", failing)

    with pytest.raises(Broken):
        guard.apply(guard.Verdict(guard.BLOCK, 0.97, ["a new network"]), superuser_request)

    assert not AnomalyEvent.objects.exists()


@pytest.mark.django_db
def test_rows_deleted_together_in_the_admin_go_with_their_audit_rows(
    superuser_request, monkeypatch
):
    KnownLocation.objects.create(
        user=superuser_request.user, label="usual", latitude=23.6, longitude=58.5
    )
    monkeypatch.setattr(audit, "record", failing)

    with pytest.raises(Broken):
        KnownLocationAdmin(KnownLocation, admin.site).delete_queryset(
            superuser_request, KnownLocation.objects.all()
        )

    assert KnownLocation.objects.count() == 1


@pytest.mark.django_db
def test_rows_deleted_together_in_the_admin_are_each_audited(superuser_request):
    for label in ("home", "office"):
        KnownLocation.objects.create(
            user=superuser_request.user, label=label, latitude=23.6, longitude=58.5
        )

    KnownLocationAdmin(KnownLocation, admin.site).delete_queryset(
        superuser_request, KnownLocation.objects.all()
    )

    assert not KnownLocation.objects.exists()
    assert AuditEvent.objects.filter(action="security.location.delete").count() == 2


@pytest.mark.django_db
def test_unlocking_an_account_does_not_wait_for_its_audit_row(admin_user, monkeypatch):
    from django.core.management import call_command

    Lockout.objects.create(user=admin_user, reason="a new network")
    monkeypatch.setattr(audit, "record", failing)

    with pytest.raises(Broken):
        call_command("dbs_security", "unlock", admin_user.get_username())

    assert not Lockout.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_a_checkpoint_reads_its_migrations_in_the_snapshot_its_rows_come_from(
    settings, tmp_path, monkeypatch
):
    settings.DBS_BACKUP_DIR = str(tmp_path / "backups")
    settings.DBS_KDF_TIME_COST = 1
    settings.DBS_KDF_MEMORY_COST = 8 * 1024
    settings.DBS_KDF_PARALLELISM = 1
    inside = []
    real = schema.snapshot

    def watched(connection):
        inside.append(connection.in_atomic_block)
        return real(connection)

    monkeypatch.setattr(schema, "snapshot", watched)

    checkpoints.take(checkpoints.BEFORE_MIGRATE)

    assert inside == [True]
