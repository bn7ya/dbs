import os
import signal
import threading
import time
from datetime import timedelta

import pytest
from django.db.models import Q
from django.utils import timezone

from dbs import audit, job_process, jobs, schedule_runner
from dbs.models import AuditEvent, BackupSchedule, Lease
from tests.isolation.hooks import BARRIER
from tests.testapp.models import Author

PASS = "isolation-pass-phrase"
SETTLE_SECONDS = 90

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def backup_dir(tmp_path, settings):
    folder = tmp_path / "backups"
    folder.mkdir()
    settings.DBS_BACKUP_DIR = str(folder)
    settings.DBS_KDF_TIME_COST = 1
    settings.DBS_KDF_MEMORY_COST = 8192
    return folder


@pytest.fixture
def children(monkeypatch):
    seen = []
    real = job_process.supervise

    def recording(child, **kwargs):
        seen.append(child)
        return real(child, **kwargs)

    monkeypatch.setattr(job_process, "supervise", recording)
    return seen


@pytest.fixture
def barrier(tmp_path, monkeypatch):
    path = tmp_path / "go"
    monkeypatch.setenv(BARRIER, str(path))
    return path


def finished(event_id):
    stop = time.monotonic() + SETTLE_SECONDS
    while time.monotonic() < stop:
        event = AuditEvent.objects.get(pk=event_id)
        held = Lease.objects.filter(owner__gt="").filter(
            Q(name__startswith=jobs.JOB_LEASE_PREFIX) | Q(name=jobs.RUNNER_LEASE)
        )
        if event.status not in audit.UNFINISHED and not held.exists():
            return event
        time.sleep(0.1)
    raise AssertionError(f"job {event_id} did not finish")


def files_in(folder):
    return sorted(name for name in os.listdir(folder))


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_a_panel_backup_runs_in_its_own_process(backup_dir, children):
    Author.objects.create(name="Ada")

    event_id = jobs.start_backup(database="default", passphrase=PASS)
    event = finished(event_id)

    assert event.status == audit.SUCCEEDED, event.detail
    assert children[0].pid != os.getpid()
    assert files_in(backup_dir) == [event.target_name]
    assert not Lease.objects.filter(name=jobs.RUNNER_LEASE, owner__gt="").exists()


def test_a_panel_restore_runs_in_its_own_process(backup_dir, children):
    Author.objects.create(name="Ada")
    backed_up = finished(jobs.start_backup(database="default", passphrase=PASS))
    Author.objects.all().delete()

    event = finished(
        jobs.start_restore(
            path=str(backup_dir / backed_up.target_name),
            name=backed_up.target_name,
            passphrase=PASS,
            dry_run=False,
        )
    )

    assert event.status == audit.SUCCEEDED, event.detail
    assert Author.objects.get().name == "Ada"
    assert len(children) == 2


def test_the_passphrase_never_reaches_the_command_line_or_environment(
    backup_dir, children, barrier, settings
):
    settings.DBS_JOB_BOOTSTRAP = "tests.isolation.hooks.slow"

    event_id = jobs.start_backup(database="default", passphrase=PASS)
    pid = children[0].pid
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            cmdline = fh.read()
        with open(f"/proc/{pid}/environ", "rb") as fh:
            environ = fh.read()
    finally:
        barrier.write_text("go")

    assert PASS.encode() not in cmdline
    assert PASS.encode() not in environ
    assert finished(event_id).status == audit.SUCCEEDED


def test_a_killed_job_is_failed_cleaned_up_and_the_next_backup_runs(
    backup_dir, children, barrier, settings
):
    settings.DBS_JOB_BOOTSTRAP = "tests.isolation.hooks.slow"
    Author.objects.create(name="Ada")

    event_id = jobs.start_backup(database="default", passphrase=PASS)
    os.kill(children[0].pid, signal.SIGKILL)
    event = finished(event_id)

    assert (event.status, event.error_code) == (audit.FAILED, job_process.KILLED)
    assert files_in(backup_dir) == []
    assert not Lease.objects.filter(owner__gt="", name__startswith="dbs.").exclude(
        name=schedule_runner.SEEN_LEASE
    ).exists()

    settings.DBS_JOB_BOOTSTRAP = ""
    again = finished(jobs.start_backup(database="default", passphrase=PASS))
    assert again.status == audit.SUCCEEDED


def test_a_job_over_its_time_limit_is_stopped(backup_dir, children, barrier, settings):
    settings.DBS_JOB_BOOTSTRAP = "tests.isolation.hooks.slow"
    settings.DBS_JOB_TIME_LIMIT = "2s"

    event = finished(jobs.start_backup(database="default", passphrase=PASS))

    assert (event.status, event.error_code) == (audit.FAILED, job_process.TIME_LIMIT)
    assert "DBS_JOB_TIME_LIMIT" in event.detail
    assert files_in(backup_dir) == []
    assert not alive(children[0].pid)


def test_a_job_over_its_memory_limit_is_stopped(backup_dir, children, barrier, settings):
    settings.DBS_JOB_BOOTSTRAP = "tests.isolation.hooks.hungry"
    settings.DBS_JOB_MEMORY_LIMIT = "400M"

    event = finished(jobs.start_backup(database="default", passphrase=PASS))

    assert (event.status, event.error_code) == (audit.FAILED, job_process.MEMORY_LIMIT)
    assert files_in(backup_dir) == []


def test_a_job_another_process_took_over_stops_without_publishing(
    backup_dir, children, barrier, settings
):
    settings.DBS_JOB_BOOTSTRAP = "tests.isolation.hooks.slow"

    event_id = jobs.start_backup(database="default", passphrase=PASS)
    Lease.objects.filter(name=jobs.job_lease(event_id)).update(
        expires_at=timezone.now() - timedelta(minutes=5)
    )
    assert jobs.recover() == 1
    deadline = time.monotonic() + SETTLE_SECONDS
    while alive(children[0].pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    barrier.write_text("go")

    event = AuditEvent.objects.get(pk=event_id)
    assert (event.status, event.error_code) == (audit.FAILED, audit.INTERRUPTED)
    assert children[0].process.wait(timeout=SETTLE_SECONDS) == job_process.EXIT_CODES[
        job_process.LEASE_LOST
    ]
    assert files_in(backup_dir) == []


def test_the_web_process_keeps_serving_while_a_job_runs(backup_dir, children, barrier, settings):
    settings.DBS_JOB_BOOTSTRAP = "tests.isolation.hooks.slow"

    event_id = jobs.start_backup(database="default", passphrase=PASS)
    answered = []
    worker = threading.Thread(target=lambda: answered.append(Author.objects.count()))
    worker.start()
    worker.join(5)
    barrier.write_text("go")

    assert answered == [0]
    assert finished(event_id).status == audit.SUCCEEDED


def test_a_scheduled_backup_runs_in_its_own_process(backup_dir):
    BackupSchedule.objects.create(enabled=True, interval="6h")
    Author.objects.create(name="Ada")

    output = schedule_runner.run_due(force=True)

    assert output is not None and os.path.isfile(output)
    assert BackupSchedule.load().last_status == audit.SUCCEEDED
