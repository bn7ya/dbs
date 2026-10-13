"""Panel backups and restores run in the background, one at a time, outside the request."""

from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone

from dbs import audit, jobs, leases
from dbs.models import AuditEvent, BackupRecord, BackupSchedule, Lease
from tests.testapp.models import Author

CREATE = "/admin/dbs/backuprecord/create/"


@pytest.fixture
def backup_dir(tmp_path, settings):
    settings.DBS_BACKUP_DIR = str(tmp_path / "backups")
    return tmp_path / "backups"


@pytest.fixture
def root(db, settings):
    settings.DBS_SETUP_WIZARD = False
    return User.objects.create_superuser("root", "root@example.com", "pw")


@pytest.fixture
def panel(root):
    client = Client()
    client.force_login(root)
    return client


def job_url(event_id):
    return f"/admin/dbs/backuprecord/jobs/{event_id}/"


@pytest.mark.django_db(transaction=True)
def test_a_panel_backup_runs_in_its_own_thread_and_outlives_the_request(
    panel, backup_dir, monkeypatch
):
    Author.objects.create(name="Ada")
    threads = []
    launch = jobs.launch
    monkeypatch.setattr(
        jobs, "launch", lambda work, name="dbs-job": threads.append(launch(work, name))
    )

    response = panel.post(CREATE, {"database": "default", "note": ""})
    threads[0].join(timeout=120)

    assert response.status_code == 302
    event = AuditEvent.objects.get(action="backup.create")
    assert response["Location"] == job_url(event.pk)
    assert threads[0].name == "dbs-job" and not threads[0].is_alive()
    assert event.status == audit.SUCCEEDED
    assert (backup_dir / event.target_name).stat().st_size == event.data["size"]
    assert leases.holder(jobs.RUNNER_LEASE) is None
    assert not Lease.objects.filter(name__startswith=jobs.JOB_LEASE_PREFIX).exists()


@pytest.mark.django_db
def test_the_job_page_refreshes_until_the_job_ends(panel, backup_dir):
    event = audit.record("backup.create", target="b.dbs", status=audit.RUNNING)
    Lease.objects.create(
        name=jobs.job_lease(event.pk), owner="w", expires_at=timezone.now() + timedelta(minutes=1)
    )

    running = panel.get(job_url(event.pk))
    audit.finish(event.pk, data={"size": 2048})
    finished = panel.get(job_url(event.pk))

    assert b'http-equiv="refresh"' in running.content
    assert b"Backing up to b.dbs" in running.content
    assert b'http-equiv="refresh"' not in finished.content
    assert b"Wrote b.dbs (2,048 bytes)" in finished.content


@pytest.mark.django_db
def test_a_job_whose_process_died_is_shown_as_interrupted(panel):
    event = audit.record("backup.restore", target="b.dbs", status=audit.RUNNING)
    Lease.objects.create(
        name=jobs.job_lease(event.pk), owner="w", expires_at=timezone.now() - timedelta(seconds=1)
    )

    page = panel.get(job_url(event.pk))

    assert b"stopped before it finished" in page.content
    event.refresh_from_db()
    assert (event.status, event.error_code) == (audit.FAILED, audit.INTERRUPTED)


@pytest.mark.django_db
def test_only_backup_and_restore_jobs_have_a_page(panel):
    other = audit.record("schedule.update")

    assert panel.get(job_url(other.pk)).status_code == 404
    assert panel.get(job_url(99999)).status_code == 404


@pytest.mark.django_db
def test_a_job_that_cannot_start_is_closed_and_frees_the_runner(backup_dir, monkeypatch):
    def refuse(work, name="dbs-job"):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(jobs, "launch", refuse)

    with pytest.raises(RuntimeError):
        jobs.start_backup(database="default")

    event = AuditEvent.objects.get(action="backup.create")
    assert event.status == audit.FAILED and "new thread" in event.detail
    assert list(backup_dir.iterdir()) == []
    jobs.Runner().take().release()


@pytest.mark.django_db
def test_panel_backups_keep_the_schedule_number(backup_dir, inline_jobs):
    BackupSchedule.objects.create(keep=1)

    first = jobs.start_backup(database="default")
    second = jobs.start_backup(database="default")

    names = [AuditEvent.objects.get(pk=pk).target_name for pk in (first, second)]
    assert sorted(path.name for path in backup_dir.iterdir()) == [names[1]]
    assert BackupRecord.objects.count() == 2
    assert AuditEvent.objects.get(action="backup.prune").data["removed"] == [names[0]]


@pytest.mark.django_db
def test_a_wrong_passphrase_fails_the_restore_job_and_keeps_the_stored_file(
    backup_dir, inline_jobs
):
    first = jobs.start_backup(database="default")
    name = AuditEvent.objects.get(pk=first).target_name

    event_id = jobs.start_restore(
        path=str(backup_dir / name), name=name, passphrase="not the passphrase"
    )

    event = AuditEvent.objects.get(pk=event_id)
    assert event.status == audit.FAILED and event.error_code == "InvalidPassphrase"
    assert (backup_dir / name).exists()
    jobs.Runner().take().release()
