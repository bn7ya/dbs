from __future__ import annotations

import ctypes
import socket
from datetime import timedelta

import pytest
from django.utils import timezone

from dbs import audit, leases
from dbs.manager import processes, recovery
from dbs.manager.activity import job_leases
from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.activity.services import ActivityService
from dbs.manager.applications.repositories import ApplicationRepository
from dbs.manager.backups.locks import TakeLock
from dbs.manager.scheduler import TASKS
from dbs.manager.servers import settling
from tests.manager.factories import make_application
from tests.manager.support import backdated


@pytest.fixture
def application(admin):
    return make_application(admin, "web-1", "10.0.0.5")


def queued_job(admin, application):
    job = ActivityService(admin).queue(
        "backup.take", subject=application, target=application.name
    )
    assert TakeLock().acquire(application.pk, job.pk)
    return job


@pytest.mark.django_db
def test_starting_the_manager_frees_the_lock_of_a_job_it_interrupted(
    admin, application
):
    job = queued_job(admin, application)

    released = recovery.recover()

    assert released == 1
    assert ActivityRepository().get(job.pk).error_code == audit.INTERRUPTED
    assert TakeLock().acquire(application.pk, 99) is True


@pytest.mark.django_db
def test_a_lock_whose_job_still_runs_is_kept(admin, application):
    job = queued_job(admin, application)
    ActivityService(None).start(job.pk)

    try:
        assert recovery.recover() == 0
        assert TakeLock().holder(application.pk) == str(job.pk)
    finally:
        ActivityService(None).succeed(job.pk)


@pytest.mark.django_db
def test_a_lock_left_by_a_finished_job_is_freed(admin, application):
    job = queued_job(admin, application)
    audit.finish(job.pk)

    assert recovery.release_abandoned_locks() == 1
    assert TakeLock().holder(application.pk) is None


@pytest.mark.django_db
def test_each_application_on_a_server_holds_its_own_lock(admin, application):
    neighbour = make_application(admin, "web-1-api", server=application.server)
    running = queued_job(admin, application)
    ActivityService(None).start(running.pk)
    finished = queued_job(admin, neighbour)
    audit.finish(finished.pk)

    try:
        assert recovery.release_abandoned_locks() == 1
        assert TakeLock().holder(application.pk) == str(running.pk)
        assert TakeLock().holder(neighbour.pk) is None
        assert TakeLock().holder(application.server_id) is None
    finally:
        ActivityService(None).succeed(running.pk)


@pytest.mark.django_db
def test_a_lock_left_on_a_removed_application_is_freed(admin, application):
    job = queued_job(admin, application)
    audit.finish(job.pk)
    ApplicationRepository().soft_delete(application)

    assert recovery.release_abandoned_locks() == 1
    assert TakeLock().holder(application.pk) is None


@pytest.mark.django_db
def test_the_sweep_frees_the_locks_of_jobs_it_finds_interrupted(
    admin, application, settings
):
    job = queued_job(admin, application)
    backdated(
        job,
        created_at=timezone.now()
        - timedelta(seconds=settings.BACKUP_TASK_TIME_LIMIT, hours=2),
    )

    assert recovery.sweep() == 1
    assert TakeLock().holder(application.pk) is None


@pytest.mark.django_db
def test_freeing_locks_never_shortens_a_settling_window(admin, application):
    until = timezone.now() + timedelta(seconds=40)
    settling.mark(application.pk, until)

    recovery.release_abandoned_locks()

    assert settling.settling_until(application.pk) == until
    assert TakeLock().acquire(application.pk, 1) is False


@pytest.mark.django_db
def test_a_job_whose_process_died_is_interrupted_and_its_lock_freed(
    admin, application, monkeypatch
):
    job = queued_job(admin, application)
    ActivityService(None).start(job.pk)
    name = f"{job_leases.PREFIX}{job.pk}"
    leases.release(name, leases.process_owner())
    leases.acquire(name, f"{socket.gethostname()}:4242", 3600)
    monkeypatch.setattr(processes, "pid_running", lambda pid: False)

    assert recovery.recover() == 1
    assert TakeLock().holder(application.pk) is None


def test_the_scheduler_probes_servers_and_sweeps_through_recovery():
    assert TASKS["probe_servers"][1].endswith("connection_service.probe_servers")
    assert TASKS["sweep_stale_jobs"][1] == "dbs.manager.recovery.sweep"


class Kernel32:
    def __init__(self, *, handle=7, exit_code=processes.STILL_ACTIVE, readable=True):
        self.handle = handle
        self.exit_code = exit_code
        self.readable = readable
        self.closed = []
        self.opened = []

    def OpenProcess(self, access, inherit, pid):
        self.opened.append((access, inherit, pid))
        return self.handle

    def GetExitCodeProcess(self, handle, code):
        if not self.readable:
            return 0
        code._obj.value = self.exit_code
        return 1

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return 1


@pytest.mark.parametrize(
    ("kernel32", "error", "running"),
    [
        (Kernel32(), 0, True),
        (Kernel32(exit_code=0), 0, False),
        (Kernel32(readable=False), 0, True),
        (Kernel32(handle=0), processes.ERROR_ACCESS_DENIED, True),
        (Kernel32(handle=0), 87, False),
    ],
)
def test_windows_asks_the_process_itself_whether_it_still_runs(kernel32, error, running):
    assert processes.windows_pid_running(4242, kernel32, lambda: error) is running
    assert kernel32.opened == [
        (processes.PROCESS_QUERY_LIMITED_INFORMATION, False, 4242)
    ]
    assert kernel32.closed == ([] if kernel32.handle == 0 else [kernel32.handle])


def test_windows_is_asked_on_windows(monkeypatch):
    kernel32 = Kernel32(exit_code=1)
    monkeypatch.setattr(processes.os, "name", "nt")
    monkeypatch.setattr(processes, "_kernel32", lambda: kernel32)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 0, raising=False)

    assert processes.pid_running(4242) is False
    assert processes.abandoned(f"{socket.gethostname()}:4242") is True


@pytest.mark.django_db
def test_the_sweep_leaves_a_long_job_that_still_renews_its_lease(
    admin, application, settings
):
    long_ago = timezone.now() - timedelta(seconds=settings.BACKUP_TASK_TIME_LIMIT, hours=3)
    renewing = queued_job(admin, application)
    ActivityService(None).start(renewing.pk)
    backdated(renewing, started_at=long_ago)
    silent = ActivityService(admin).queue("backup.take", subject=application)
    ActivityService(None).start(silent.pk)
    backdated(silent, started_at=long_ago)
    from dbs.models import Lease

    Lease.objects.filter(name=f"{job_leases.PREFIX}{silent.pk}").update(
        renewed_at=long_ago
    )
    job_leases.hold(renewing.pk)

    assert recovery.sweep() == 1
    assert ActivityRepository().find_joined(renewing.pk).status == audit.RUNNING
    assert ActivityRepository().find_joined(silent.pk).status == audit.FAILED
