"""What must be true together is written in one transaction, or not at all."""

import pytest
from django.db import DatabaseError
from rest_framework.test import APIClient

from dbs import audit
from dbs.manager.accounts.models import RecoveryCode
from dbs.manager.accounts.services import AccountService
from dbs.manager.activity import heartbeat, job_leases
from dbs.manager.activity.services import ActivityService
from dbs.models import AuditEvent
from tests.manager.accounts.support import enrolled
from tests.manager.support import PASSWORD, logged

ANOTHER_PASSWORD = "another-horse-another-staple"


class Broken(DatabaseError):
    pass


def failing(*args, **kwargs):
    raise Broken("the database went away")


@pytest.fixture
def jobs(db):
    return ActivityService(None)


@pytest.fixture
def queued(jobs):
    job = jobs.queue("backup.take", target="shop")
    yield job
    heartbeat.end(job.pk)


def status_of(job):
    return AuditEvent.objects.get(pk=job.pk).status


def test_a_job_starts_running_with_its_lease_or_stays_queued(jobs, queued, monkeypatch):
    monkeypatch.setattr(job_leases, "hold", failing)

    with pytest.raises(Broken):
        jobs.start(queued.pk)

    assert status_of(queued) == audit.QUEUED


@pytest.mark.parametrize("ending", ["succeed", "fail"])
def test_a_job_ends_and_lets_its_lease_go_or_stays_running(jobs, queued, monkeypatch, ending):
    jobs.start(queued.pk)
    monkeypatch.setattr(job_leases, "let_go", failing)

    with pytest.raises(Broken):
        if ending == "succeed":
            jobs.succeed(queued.pk)
        else:
            jobs.fail(queued.pk, RuntimeError("the server did not answer"))

    assert status_of(queued) == audit.RUNNING
    assert job_leases.live() == [queued.pk]


def test_a_job_that_ends_is_finished_and_holds_no_lease(jobs, queued):
    jobs.start(queued.pk)

    jobs.succeed(queued.pk, {"size": 1})

    assert status_of(queued) == audit.SUCCEEDED
    assert job_leases.live() == []


def test_a_password_changes_with_its_audit_row_or_not_at_all(admin, monkeypatch):
    monkeypatch.setattr(ActivityService, "record", failing)

    with pytest.raises(Broken):
        AccountService(admin).change_password(PASSWORD, ANOTHER_PASSWORD)

    admin.refresh_from_db()
    assert admin.check_password(PASSWORD)


def test_a_changed_password_is_in_the_audit_trail(admin):
    AccountService(admin).change_password(PASSWORD, ANOTHER_PASSWORD)

    admin.refresh_from_db()
    assert admin.check_password(ANOTHER_PASSWORD)
    assert [entry.target_name for entry in logged("account.password")] == ["sara"]


def test_a_recovery_code_is_used_up_with_its_audit_row_or_not_at_all(admin, monkeypatch):
    codes = enrolled(admin)
    client = APIClient()
    client.post("/api/auth/login/", {"username": "sara", "password": PASSWORD})
    monkeypatch.setattr(ActivityService, "record", failing)

    with pytest.raises(Broken):
        client.post("/api/auth/two-factor/", {"recovery_code": codes[0]})

    assert RecoveryCode.objects.filter(used_at__isnull=True).count() == len(codes)
