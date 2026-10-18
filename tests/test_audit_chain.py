"""The audit trail: every DBS write recorded, the actor's name kept, and rows chained by hash."""

import errno
from io import StringIO

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError
from django.test import Client

from dbs import audit, jobs
from dbs.exceptions import CorruptionError, DBSError, InvalidPassphrase
from dbs.models import AuditEvent, BackupRecord, KnownLocation, SecurityPolicy

PASS = "chain-pass-phrase"


@pytest.fixture
def root(db, settings):
    settings.DBS_SETUP_WIZARD = False
    settings.DBS_TRUSTED_NETWORKS = ["127.0.0.0/8"]
    return User.objects.create_superuser("root", "root@example.com", "pw")


@pytest.fixture
def panel(root):
    client = Client()
    client.force_login(root)
    return client


@pytest.fixture
def sealing(django_capture_on_commit_callbacks):
    def capture():
        return django_capture_on_commit_callbacks(execute=True)

    return capture


def chained():
    sealed = AuditEvent.objects.exclude(chain_index=None).order_by("chain_index")
    return list(sealed.values_list("chain_index", flat=True))


@pytest.mark.django_db
def test_each_finished_row_is_sealed_onto_the_one_before(sealing):
    with sealing():
        first = audit.record("backup.create", target="a.dbs", data={"size": 1})
    with sealing():
        second = audit.record("backup.validate", target="a.dbs", data={"ok": True})

    first.refresh_from_db()
    second.refresh_from_db()
    assert (first.chain_index, second.chain_index) == (1, 2)
    assert first.chain_hash == audit.link("", first)
    assert second.chain_hash == audit.link(first.chain_hash, second)
    check = audit.verify_chain()
    assert check.intact and check.checked == 2 and check.head == second.chain_hash


@pytest.mark.django_db
def test_a_running_row_is_sealed_when_it_ends(sealing):
    with sealing():
        running = audit.record("backup.create", status=audit.RUNNING)
    running.refresh_from_db()
    assert running.chain_index is None

    with sealing():
        audit.finish(running.pk, data={"size": 3})

    running.refresh_from_db()
    assert running.chain_index == 1
    assert audit.verify_chain().intact


@pytest.mark.django_db
def test_interrupted_rows_are_sealed_too(sealing):
    with sealing():
        lost = audit.record("backup.restore", status=audit.RUNNING)
        audit.interrupt(events=[lost.pk])

    lost.refresh_from_db()
    assert (lost.status, lost.chain_index) == (audit.FAILED, 1)


@pytest.mark.django_db
def test_rows_written_before_the_chain_are_caught_up_in_order(sealing):
    older = [audit.record("backup.create", target=f"{n}.dbs") for n in range(3)]

    with sealing():
        audit.record("schedule.update")

    assert chained() == [1, 2, 3, 4]
    assert AuditEvent.objects.get(pk=older[0].pk).chain_index == 1
    assert audit.verify_chain().intact


@pytest.mark.django_db
def test_a_backlog_is_sealed_a_batch_at_a_time_and_reported_until_then():
    for n in range(3):
        audit.record("backup.create", target=f"{n}.dbs")
    audit.record("backup.create", status=audit.RUNNING)

    assert audit.seal_pending(limit=2) == 2
    out = StringIO()
    call_command("dbs", "audit", "verify", stdout=out)

    assert chained() == [1, 2]
    assert "intact: 2 rows checked" in out.getvalue()
    assert "1 finished rows are not sealed yet" in out.getvalue()
    assert "1 rows are still running" in out.getvalue()
    assert audit.seal_pending() == 1 and audit.seal_pending() == 0


@pytest.mark.django_db
def test_a_changed_row_breaks_the_chain_at_that_row(sealing):
    with sealing():
        rows = [audit.record("backup.create", target=f"{n}.dbs") for n in range(3)]
    AuditEvent.objects.filter(pk=rows[1].pk).update(status="succeeded", detail="rewritten")

    check = audit.verify_chain()

    assert not check.intact
    assert (check.broken_at, check.event_id) == (2, rows[1].pk)
    assert "changed after it was sealed" in check.reason


@pytest.mark.django_db
def test_a_deleted_row_breaks_the_chain(sealing):
    with sealing():
        rows = [audit.record("backup.create", target=f"{n}.dbs") for n in range(3)]
    AuditEvent.objects.filter(pk=rows[0].pk).delete()

    check = audit.verify_chain()

    assert check.broken_at == 1 and "missing" in check.reason


@pytest.mark.django_db
def test_dbs_audit_verify_reports_the_first_broken_link(sealing):
    with sealing():
        rows = [audit.record("backup.create", target=f"{n}.dbs") for n in range(2)]
    out = StringIO()

    call_command("dbs", "audit", "verify", stdout=out)

    assert "intact: 2 rows checked" in out.getvalue()
    AuditEvent.objects.filter(pk=rows[1].pk).update(target_name="other.dbs")
    with pytest.raises(CommandError) as excinfo:
        call_command("dbs", "audit", "verify", stdout=StringIO())
    assert "broken at link 2" in str(excinfo.value)


@pytest.mark.django_db
def test_a_panel_write_keeps_the_username_after_the_user_is_deleted(panel, root, sealing):
    with sealing():
        panel.post(
            "/admin/dbs/panel/setup/",
            {"level": "relaxed", "trusted_networks": "127.0.0.0/8"},
        )
    event = AuditEvent.objects.get(action="security.setup")
    assert event.data["actor_username"] == "root"

    root.delete()
    event.refresh_from_db()

    assert event.actor is None
    assert event.actor_name == "root"
    assert str(event) == "security.setup by root"
    assert audit.verify_chain().intact


@pytest.mark.django_db
def test_every_dbs_admin_write_is_audited(panel):
    policy = SecurityPolicy.load()
    form = {
        "level": "strict",
        "expected_networks": "",
        "trusted_networks": "",
        "warn_threshold": 0.5,
        "logout_threshold": 0.7,
        "learning_logins": 5,
        "idle_timeout_minutes": 30,
        "notify_emails": "",
    }
    panel.post(f"/admin/dbs/securitypolicy/{policy.pk}/change/", form)
    user = User.objects.get(username="root")
    panel.post(
        "/admin/dbs/knownlocation/add/",
        {"user": user.pk, "label": "office", "latitude": 1.5, "longitude": 2.5, "radius_km": 50},
    )
    location = KnownLocation.objects.get()
    panel.post(f"/admin/dbs/knownlocation/{location.pk}/delete/", {"post": "yes"})
    record = BackupRecord.objects.create(filename="old.dbs")
    panel.post(f"/admin/dbs/backuprecord/{record.pk}/delete/", {"post": "yes"})
    schedule = panel.get("/admin/dbs/backupschedule/")["Location"]
    panel.post(schedule, {"enabled": "", "interval": "12h", "keep": 3, "database": "default"})

    rows = {
        event.action: event
        for event in AuditEvent.objects.exclude(action__startswith="auth.")
    }
    assert set(rows) == {
        "security.policy.update",
        "security.location.add",
        "security.location.delete",
        "backup.record.delete",
        "schedule.update",
    }
    assert "logout_threshold" in rows["security.policy.update"].data["fields"]
    assert rows["security.location.add"].target_name == "root: office"
    assert "1.5" not in rows["security.location.delete"].target_name
    assert rows["backup.record.delete"].target_name == "old.dbs"
    assert rows["schedule.update"].data["keep"] == 3
    assert all(event.data["actor_username"] == "root" for event in rows.values())


@pytest.mark.django_db
def test_an_unexpected_failure_in_a_panel_job_is_audited_as_unexpected(
    tmp_path, settings, monkeypatch, inline_jobs
):
    from dbs.engine import backup

    settings.DBS_BACKUP_DIR = str(tmp_path)

    def explode(*args, **kwargs):
        raise ValueError("bug")

    monkeypatch.setattr(backup, "write_backup", explode)

    with pytest.raises(ValueError):
        jobs.start_backup(database="default")

    event = AuditEvent.objects.get(action="backup.create")
    assert (event.status, event.error_code) == (audit.FAILED, "unexpected")
    jobs.Runner().take().release()


@pytest.mark.parametrize(
    "exc, code",
    [
        (DBSError("x"), "DBSError"),
        (InvalidPassphrase("x"), "InvalidPassphrase"),
        (CorruptionError("x"), "CorruptionError"),
        (CommandError("x"), "CommandError"),
        (ValueError("x"), "unexpected"),
        (OSError(errno.ENOSPC, "No space left on device"), "disk_full"),
        (OSError(errno.EDQUOT, "Disk quota exceeded"), "disk_full"),
        (PermissionError(errno.EACCES, "Permission denied"), "permission_denied"),
        (OSError(errno.EROFS, "Read-only file system"), "read_only"),
        (OSError(errno.EIO, "Input/output error"), "unexpected"),
        (OperationalError("server closed the connection unexpectedly"), "database_failed"),
        (KeyboardInterrupt(), "interrupted"),
        (jobs.Busy("x"), "busy"),
    ],
)
def test_error_codes_name_what_failed(exc, code):
    assert audit.error_code_for(exc) == code


def test_a_command_error_carries_the_code_of_a_full_disk_but_not_of_any_os_error():
    def wrapped(cause):
        try:
            try:
                raise cause
            except OSError as found:
                raise CommandError("Cannot write") from found
        except CommandError as exc:
            return audit.error_code_for(exc)

    assert wrapped(OSError(errno.ENOSPC, "No space left on device")) == "disk_full"
    assert wrapped(OSError(errno.EIO, "Input/output error")) == "CommandError"


def test_a_command_error_carries_the_code_of_its_cause():
    try:
        try:
            raise CorruptionError("bad block")
        except CorruptionError as cause:
            raise CommandError("Backup failed") from cause
    except CommandError as exc:
        assert audit.error_code_for(exc) == "CorruptionError"


@pytest.mark.django_db
def test_no_dbs_command_deletes_audit_rows(settings):
    from datetime import timedelta

    from django.utils import timezone

    settings.DBS_SECURITY_RETENTION_DAYS = 0
    event = audit.record("backup.create")
    AuditEvent.objects.filter(pk=event.pk).update(created_at=timezone.now() - timedelta(days=400))
    out = StringIO()

    call_command("dbs", "security", "purge", stdout=out)

    assert AuditEvent.objects.filter(pk=event.pk).exists()
    assert "audit trail is kept" in out.getvalue()
