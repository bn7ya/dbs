from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.exceptions import NotFound

from dbs import audit
from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.activity.services import ActivityService, sweep_stale_jobs
from dbs.manager.middleware import request_origin
from dbs.models import AuditEvent


def stored(entry_id):
    return ActivityRepository().get(entry_id)


@pytest.mark.django_db
def test_a_queued_job_has_an_actor_an_address_and_no_start(admin):
    with request_origin({"REMOTE_ADDR": "203.0.113.9"}):
        job = ActivityService(admin).queue("backup.take", target="web-1")

    job = stored(job.pk)
    assert job.status == audit.QUEUED
    assert (job.action, job.target_name) == ("backup.take", "web-1")
    assert job.actor == admin and job.remote_addr == "203.0.113.9"
    assert (job.started_at, job.finished_at) == (None, None)
    assert (job.data, job.error_code) == ({}, "")


@pytest.mark.django_db
def test_a_job_runs_then_succeeds_with_its_result(admin):
    job = ActivityService(admin).queue("backup.take")
    worker = ActivityService(None)

    started = worker.start(job.pk)
    running = stored(job.pk)
    worker.succeed(job.pk, {"backup": "id", "size": 10})

    assert started.pk == job.pk and started.actor == admin
    assert running.status == audit.RUNNING and running.started_at is not None
    done = stored(job.pk)
    assert done.status == audit.SUCCEEDED and done.succeeded
    assert done.data == {"backup": "id", "size": 10}
    assert done.finished_at >= done.started_at


@pytest.mark.django_db
def test_a_job_fails_with_the_code_of_its_error(admin):
    job = ActivityService(admin).queue("backup.take")
    worker = ActivityService(None)
    worker.start(job.pk)

    worker.fail(job.pk, NotFound(), {"output": "exit 1"})

    failed = stored(job.pk)
    assert failed.status == audit.FAILED
    assert failed.error_code == "not_found"
    assert failed.data == {"output": "exit 1"}


@pytest.mark.django_db
def test_an_error_without_a_code_fails_a_job_as_unexpected_and_keeps_its_data(admin):
    job = ActivityService(admin).queue("backup.verify", detail={"plan": "id"})

    ActivityService(None).fail(job.pk, RuntimeError("boom"))

    assert stored(job.pk).error_code == "unexpected"
    assert stored(job.pk).data == {"plan": "id"}


@pytest.mark.django_db
def test_a_running_job_does_not_start_twice_and_a_finished_one_never_does(admin):
    service = ActivityService(admin)
    finished = service.queue("backup.take")
    service.start(finished.pk)
    service.succeed(finished.pk)

    assert service.start(finished.pk) is None
    assert stored(finished.pk).status == audit.SUCCEEDED
    assert service.start(999999) is None


@pytest.mark.django_db
def test_a_tracked_action_records_its_outcome(admin):
    service = ActivityService(admin)
    with service.track("server.check", target="web-1") as entry:
        entry.detail = {"status": "ok"}

    with (
        pytest.raises(NotFound),
        service.track("server.check", target="web-2") as entry,
    ):
        entry.detail = {"status": "failed"}
        raise NotFound()

    ok, failed = (stored(e.pk) for e in AuditEvent.objects.order_by("id"))
    assert (ok.status, ok.data) == (audit.SUCCEEDED, {"status": "ok"})
    assert (failed.status, failed.error_code) == (audit.FAILED, "not_found")
    assert failed.data == {"status": "failed"}


@pytest.mark.django_db
def test_stale_jobs_are_interrupted_and_fresh_ones_are_left(admin, settings):
    settings.BACKUP_TASK_TIME_LIMIT = 60
    service = ActivityService(admin)
    stale = service.queue("backup.take")
    fresh = service.queue("backup.take")
    AuditEvent.objects.filter(pk=stale.pk).update(
        created_at=timezone.now() - timedelta(hours=2)
    )

    sweep_stale_jobs()

    assert (stored(stale.pk).status, stored(stale.pk).error_code) == (
        audit.FAILED,
        audit.INTERRUPTED,
    )
    assert stored(fresh.pk).status == audit.QUEUED
