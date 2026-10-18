"""The backup health report shown in the panel and printed by `manage.py dbs health`."""

import json
from datetime import timedelta
from io import StringIO

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from dbs import audit, health, leases, schedule_runner
from dbs.models import AuditEvent, BackupRecord, BackupSchedule


def checks(result):
    return {check.name: check for check in result.checks}


def backed_up(ago, size=1024):
    event = audit.record("backup.create", target="b.dbs", data={"size": size})
    AuditEvent.objects.filter(pk=event.pk).update(created_at=timezone.now() - ago)


@pytest.fixture
def backup_dir(tmp_path, settings):
    settings.DBS_BACKUP_DIR = str(tmp_path)
    return tmp_path


@pytest.fixture
def scheduled(db):
    return BackupSchedule.objects.create(enabled=True, interval="6h")


@pytest.mark.django_db
def test_a_project_that_never_backed_up_is_flagged(backup_dir, scheduled):
    result = health.report()

    assert checks(result)["last backup"].status == health.ERROR
    assert result.status == health.ERROR


@pytest.mark.django_db
def test_a_fresh_backup_is_healthy(backup_dir, scheduled, settings):
    settings.DBS_SCHEDULER = "thread"
    backed_up(timedelta(hours=1))
    leases.acquire(schedule_runner.SEEN_LEASE, "worker", 180)

    result = health.report()

    assert checks(result)["last backup"].status == health.OK
    assert checks(result)["scheduler"].status == health.OK
    assert result.last_backup_at is not None


@pytest.mark.django_db
def test_a_late_backup_warns_and_a_very_late_one_fails(backup_dir, scheduled):
    backed_up(timedelta(hours=12))
    assert checks(health.report())["last backup"].status == health.WARN

    AuditEvent.objects.update(created_at=timezone.now() - timedelta(days=2))
    assert checks(health.report())["last backup"].status == health.ERROR


@pytest.mark.django_db
def test_the_newest_backup_missing_from_disk_is_an_error(backup_dir):
    BackupRecord.objects.create(filename="gone.dbs", location=str(backup_dir / "gone.dbs"))

    assert checks(health.report())["newest file"].status == health.ERROR


@pytest.mark.django_db
def test_an_unset_backup_directory_warns(settings):
    settings.DBS_BACKUP_DIR = None

    assert checks(health.report())["backup directory"].status == health.WARN


@pytest.mark.django_db
def test_a_backup_directory_that_cannot_be_created_is_an_error(settings, tmp_path):
    blocker = tmp_path / "a-file"
    blocker.write_text("not a folder")
    settings.DBS_BACKUP_DIR = str(blocker / "backups")

    assert checks(health.report())["backup directory"].status == health.ERROR


@pytest.mark.django_db
def test_a_nested_backup_directory_not_created_yet_is_writable(settings, tmp_path):
    settings.DBS_BACKUP_DIR = str(tmp_path / "nested" / "backups")

    assert checks(health.report())["backup directory"].status == health.OK


@pytest.mark.django_db
def test_a_silent_scheduler_warns(backup_dir, scheduled, settings):
    settings.DBS_SCHEDULER = "thread"
    assert checks(health.report())["scheduler"].status == health.WARN


@pytest.mark.django_db
def test_a_recent_failure_is_reported(backup_dir):
    audit.record("backup.create", status=audit.FAILED, detail="disk full")

    assert "disk full" in checks(health.report())["recent failure"].message


@pytest.mark.django_db
def test_the_command_prints_json(backup_dir, scheduled):
    backed_up(timedelta(minutes=5))
    out = StringIO()

    call_command("dbs", "health", "--json", stdout=out)

    payload = json.loads(out.getvalue())
    assert payload["status"] in (health.OK, health.WARN, health.ERROR)
    assert {"name", "status", "message"} <= set(payload["checks"][0])
    assert payload["last_backup_at"] and payload["generated_at"]
    assert payload["schedule"]["enabled"] is True
    assert payload["schedule"]["interval_seconds"] > 0
    assert payload["schedule"]["mode"] == "off"
    assert 1 <= payload["schedule"]["keep"] <= 5


@pytest.mark.django_db
def test_the_panel_shows_the_report(backup_dir, settings):
    settings.DBS_SETUP_WIZARD = False
    client = Client()
    client.force_login(User.objects.create_superuser("root", "root@example.com", "pw"))

    response = client.get("/admin/dbs/panel/health/")

    assert response.status_code == 200
    assert b"Backup health" in response.content


@pytest.mark.django_db
def test_the_job_process_is_described(settings, monkeypatch):
    settings.DBS_JOB_PROCESS = True
    settings.DBS_JOB_TIME_LIMIT = "2h"
    settings.DBS_JOB_MEMORY_LIMIT = "1G"
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "tests.settings")

    check = checks(health.report())["job process"]

    assert check.status == health.OK
    assert "2 hours" in check.message and "1024 MiB" in check.message


@pytest.mark.django_db
def test_jobs_in_the_web_process_are_named(settings):
    settings.DBS_JOB_PROCESS = False

    assert checks(health.report())["job process"].status == health.INFO
