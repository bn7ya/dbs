"""The audit trail: every backup, restore and validation records its own outcome, with no source."""

import hashlib
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError

from dbs import audit
from dbs.models import AuditEvent, BackupRecord
from tests.testapp.models import Author

PASS = "audit-pass-phrase"
FAST = {"kdf_time": 1, "kdf_memory": 8192}

AUDIT_FIELDS = {
    "id",
    "actor",
    "action",
    "target_name",
    "detail",
    "data",
    "status",
    "error_code",
    "subject",
    "remote_addr",
    "succeeded",
    "started_at",
    "finished_at",
    "created_at",
}


def backup(path):
    call_command("dbs_backup", str(path), passphrase=PASS, stdout=StringIO(), **FAST)


def test_the_audit_trail_has_no_field_that_names_a_source():
    names = {field.name for field in AuditEvent._meta.get_fields()}

    assert names == AUDIT_FIELDS


@pytest.mark.django_db
def test_a_command_line_backup_records_itself(tmp_path):
    Author.objects.create(name="Ada")
    path = tmp_path / "nightly.dbs"

    backup(path)

    event = AuditEvent.objects.get(action="backup.create")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert event.status == audit.SUCCEEDED and event.succeeded
    assert event.actor is None and event.remote_addr == ""
    assert event.subject == ""
    assert event.target_name == "nightly.dbs"
    assert event.data["sha256"] == digest
    assert event.data["size"] == path.stat().st_size
    assert event.data["database"] == "default"
    assert event.duration is not None
    stored = BackupRecord.objects.get()
    assert stored.filename == "nightly.dbs" and stored.sha256 == digest
    assert stored.location == str(path)


@pytest.mark.django_db
def test_a_failed_backup_records_its_failure(tmp_path, monkeypatch):
    from dbs.exceptions import DBSError

    def explode(*args, **kwargs):
        raise DBSError("disk full")

    monkeypatch.setattr("dbs.management.commands.dbs_backup.create_backup", explode)

    with pytest.raises(CommandError):
        backup(tmp_path / "broken.dbs")

    event = AuditEvent.objects.get(action="backup.create")
    assert event.status == audit.FAILED and not event.succeeded
    assert event.error_code == "CommandError"
    assert "disk full" in event.detail
    assert not BackupRecord.objects.exists()


@pytest.mark.django_db
def test_an_audit_write_that_fails_never_fails_the_backup(tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        raise DatabaseError("read-only replica")

    monkeypatch.setattr(audit, "record", refuse)
    path = tmp_path / "quiet.dbs"

    backup(path)

    assert path.exists()


@pytest.mark.django_db
def test_restore_and_validate_record_themselves(tmp_path):
    Author.objects.create(name="Grace")
    path = tmp_path / "restore-me.dbs"
    backup(path)
    Author.objects.all().delete()

    call_command("dbs_validate", str(path), stdout=StringIO())
    call_command("dbs_restore", str(path), passphrase=PASS, stdout=StringIO())

    validated = AuditEvent.objects.get(action="backup.validate")
    restored = AuditEvent.objects.get(action="backup.restore")
    assert validated.data["ok"] is True
    assert restored.status == audit.SUCCEEDED
    assert restored.data["records"] >= 1
    assert restored.data["dry_run"] is False
    assert Author.objects.filter(name="Grace").exists()


@pytest.mark.django_db
def test_a_restore_with_the_wrong_passphrase_is_recorded_as_failed(tmp_path):
    path = tmp_path / "locked.dbs"
    backup(path)

    with pytest.raises(CommandError):
        call_command("dbs_restore", str(path), passphrase="not-it", stdout=StringIO())

    event = AuditEvent.objects.get(action="backup.restore")
    assert event.status == audit.FAILED


@pytest.mark.django_db
def test_a_job_moves_from_queued_to_running_to_succeeded():
    job = audit.queue("backup.take", target="web-1", subject="server-1", data={"a": 1})
    assert job.status == audit.QUEUED and not job.succeeded
    assert job.started_at is None and job.finished_at is None

    running = audit.start(job.pk)
    assert running.status == audit.RUNNING and running.started_at is not None

    audit.finish(job.pk, data={"backup": "b-1"})
    job.refresh_from_db()
    assert job.status == audit.SUCCEEDED and job.succeeded
    assert job.data == {"backup": "b-1"} and job.finished_at is not None
    assert audit.start(job.pk) is None


@pytest.mark.django_db
def test_a_failed_job_keeps_its_data_unless_given_new_data():
    job = audit.queue("backup.verify", data={"backup": "b-1"})
    audit.start(job.pk)

    audit.fail(job.pk, "backup_missing")
    job.refresh_from_db()

    assert job.status == audit.FAILED and not job.succeeded
    assert job.error_code == "backup_missing" and job.data == {"backup": "b-1"}


@pytest.mark.django_db
def test_a_finished_job_is_never_changed_again():
    job = audit.queue("backup.take")
    audit.start(job.pk)
    audit.finish(job.pk)

    assert audit.fail(job.pk, "late") == 0
    job.refresh_from_db()
    assert job.status == audit.SUCCEEDED and job.error_code == ""


@pytest.mark.django_db
def test_interrupt_fails_every_unfinished_job_and_leaves_finished_ones():
    from datetime import timedelta

    from django.utils import timezone

    queued = audit.queue("backup.take")
    running = audit.queue("backup.run")
    audit.start(running.pk)
    finished = audit.record("backup.create")
    fresh = audit.queue("backup.verify")
    AuditEvent.objects.filter(pk__in=[queued.pk, running.pk]).update(
        created_at=timezone.now() - timedelta(hours=2),
        started_at=timezone.now() - timedelta(hours=2),
    )

    assert audit.interrupt(idle_since=timezone.now() - timedelta(hours=1)) == 2
    assert audit.interrupt() == 1

    statuses = {
        event.pk: (event.status, event.error_code) for event in AuditEvent.objects.all()
    }
    assert statuses[queued.pk] == (audit.FAILED, audit.INTERRUPTED)
    assert statuses[running.pk] == (audit.FAILED, audit.INTERRUPTED)
    assert statuses[fresh.pk] == (audit.FAILED, audit.INTERRUPTED)
    assert statuses[finished.pk] == (audit.SUCCEEDED, "")
