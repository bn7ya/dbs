"""The backup frequency set in the panel, and the scheduler that follows it."""

from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from dbs import leases, schedule_runner
from dbs.forms import BackupScheduleForm
from dbs.models import AuditEvent, BackupRecord, BackupSchedule
from tests.testapp.models import Author


@pytest.fixture
def backup_dir(tmp_path, settings):
    directory = tmp_path / "backups"
    settings.DBS_BACKUP_DIR = str(directory)
    return directory


def form(**fields):
    data = {"enabled": True, "interval": "6h", "keep": 3, "database": "default"}
    data.update(fields)
    return BackupScheduleForm(data={k: v for k, v in data.items() if v is not None})


@pytest.mark.django_db
def test_the_first_schedule_is_seeded_from_settings(settings):
    settings.DBS_SCHEDULE_INTERVAL = "12h"
    settings.DBS_SCHEDULE_KEEP = 4

    schedule = BackupSchedule.load()

    assert (schedule.interval, schedule.keep, schedule.enabled) == ("12h", 4, False)
    assert BackupSchedule.load().pk == schedule.pk
    assert BackupSchedule.objects.count() == 1


@pytest.mark.django_db
def test_an_unreadable_or_too_frequent_interval_is_refused(backup_dir):
    assert "interval" in form(interval="often").errors
    assert "interval" in form(interval="1m").errors
    assert form().is_valid()


@pytest.mark.django_db
def test_the_schedule_cannot_be_turned_on_without_a_backup_directory(settings):
    settings.DBS_BACKUP_DIR = None

    assert not form().is_valid()
    assert form(enabled=None).is_valid()


@pytest.mark.django_db
def test_a_lease_has_one_holder_until_it_expires():
    assert leases.acquire("job", "first", 60)
    assert not leases.acquire("job", "second", 60)
    assert leases.acquire("job", "first", 60)

    leases.release("job", "first")

    assert leases.acquire("job", "second", 60)


@pytest.mark.django_db
def test_an_expired_lease_is_taken_over():
    from dbs.models import Lease

    leases.acquire("job", "crashed", 60)
    Lease.objects.filter(name="job").update(expires_at=timezone.now() - timedelta(seconds=1))

    assert leases.acquire("job", "survivor", 60)
    assert leases.holder("job").owner == "survivor"


@pytest.mark.django_db
def test_a_due_schedule_backs_up_once_per_interval(backup_dir):
    Author.objects.create(name="Ada")
    BackupSchedule.objects.create(enabled=True, interval="6h", keep=2)
    now = timezone.now()

    first = schedule_runner.run_due(now=now)
    second = schedule_runner.run_due(now=now)

    assert first is not None and second is None
    assert len(list(backup_dir.iterdir())) == 1
    schedule = BackupSchedule.load()
    assert schedule.last_status == "succeeded"
    assert schedule.next_run_at == now + timedelta(hours=6)
    event = AuditEvent.objects.get(action="backup.create")
    assert event.actor is None and event.data["size"] > 0
    assert BackupRecord.objects.get().filename == event.target_name


@pytest.mark.django_db
def test_a_schedule_held_by_another_worker_is_left_alone(backup_dir):
    BackupSchedule.objects.create(enabled=True, interval="6h")
    leases.acquire(schedule_runner.SCHEDULE_LEASE, "other-worker", 600)

    assert schedule_runner.run_due() is None
    assert not backup_dir.exists()


@pytest.mark.django_db
def test_a_disabled_schedule_never_runs(backup_dir):
    BackupSchedule.objects.create(enabled=False, interval="6h")

    assert schedule_runner.run_due() is None


@pytest.mark.django_db
def test_retention_prunes_and_records_what_it_removed(backup_dir):
    BackupSchedule.objects.create(enabled=True, interval="6h", keep=1)

    schedule_runner.run_due(force=True)
    schedule_runner.run_due(force=True)

    assert len(list(backup_dir.iterdir())) == 1
    pruned = AuditEvent.objects.get(action="backup.prune")
    assert len(pruned.data["removed"]) == 1


@pytest.mark.django_db
def test_the_schedule_command_follows_the_panel(backup_dir):
    BackupSchedule.objects.create(enabled=True, interval="6h", keep=2)
    out = StringIO()

    call_command("dbs_schedule", "--once", stdout=out)

    assert len(list(backup_dir.iterdir())) == 1
    assert "complete" in out.getvalue()


def test_the_off_mode_starts_no_thread(settings, monkeypatch):
    settings.DBS_SCHEDULER = "off"
    monkeypatch.setitem(schedule_runner._started_in, "pid", None)

    assert schedule_runner.ensure_started() is False


def test_the_thread_mode_starts_one_thread_per_process(settings, monkeypatch):
    started = []

    class FakeThread:
        def __init__(self, target, name, daemon):
            started.append(name)

        def start(self):
            pass

    settings.DBS_SCHEDULER = "thread"
    monkeypatch.setitem(schedule_runner._started_in, "pid", None)
    monkeypatch.setattr(schedule_runner.threading, "Thread", FakeThread)

    assert schedule_runner.ensure_started() is True
    assert schedule_runner.ensure_started() is False
    assert started == ["dbs-scheduler"]


@pytest.mark.django_db
def test_the_admin_redirects_to_the_one_schedule(client, django_user_model, backup_dir, settings):
    settings.DBS_SETUP_WIZARD = False
    admin = django_user_model.objects.create_superuser("root", "r@example.com", "pw")
    client.force_login(admin)

    response = client.get("/admin/dbs/backupschedule/")

    assert response.status_code == 302
    assert response["Location"].endswith(f"/admin/dbs/backupschedule/{BackupSchedule.load().pk}/change/")
