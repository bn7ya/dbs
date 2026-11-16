"""Restoring a checkpoint in this process: tables rebuilt, rows and records put back."""

from io import StringIO

import pytest
from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder

from dbs import audit, checkpoints, create_backup, restore_backup, schedule_runner
from dbs.engine import schema
from dbs.exceptions import RestoreError
from dbs.models import AuditEvent, KnownLocation
from tests.conftest import FAST_KDF
from tests.payloads import container_of

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def quick(settings, tmp_path, monkeypatch):
    settings.DBS_BACKUP_DIR = str(tmp_path / "backups")
    settings.DBS_KDF_TIME_COST = 1
    settings.DBS_KDF_MEMORY_COST = 8 * 1024
    settings.DBS_KDF_PARALLELISM = 1
    return tmp_path / "backups"


def passphrase():
    return schedule_runner.unattended_passphrase()


def populated():
    staff = Group.objects.create(name="staff")
    staff.permissions.add(Permission.objects.get(codename="add_user"))
    ada = User.objects.create_user("ada", password="correct-horse")
    ada.groups.add(staff)
    User.objects.create_user("grace")
    return ada


def test_a_checkpoint_puts_back_the_rows_it_holds_and_none_written_since(quick):
    ada = populated()
    taken = checkpoints.take(checkpoints.BEFORE_MIGRATE)
    User.objects.filter(username="grace").delete()
    User.objects.create_user("late")
    Group.objects.create(name="late")

    result = restore_backup(taken.path, passphrase(), flush=True)

    assert sorted(User.objects.values_list("username", flat=True)) == ["ada", "grace"]
    assert list(Group.objects.values_list("name", flat=True)) == ["staff"]
    assert list(User.objects.get(pk=ada.pk).groups.values_list("name", flat=True)) == ["staff"]
    assert Group.objects.get().permissions.get().codename == "add_user"
    assert User.objects.get(pk=ada.pk).check_password("correct-horse")
    assert result.schema_rebuilt and result.records_loaded > 0
    assert "auth_user" in result.tables_rebuilt and "auth_user_groups" in result.tables_rebuilt
    assert not [table for table in result.tables_rebuilt if table.startswith("dbs_")]
    assert (result.migrations_unapplied, result.migrations_recorded) == ([], [])


def test_new_rows_get_keys_after_the_ones_put_back(quick):
    populated()
    taken = checkpoints.take(checkpoints.BEFORE_MIGRATE)
    highest = max(User.objects.values_list("pk", flat=True))

    restore_backup(taken.path, passphrase(), flush=True)

    assert User.objects.create_user("next").pk > highest
    assert ContentType.objects.get_for_model(User).model == "user"


def test_the_migration_records_are_put_back_and_those_of_dbs_left_alone(quick):
    taken = checkpoints.take(checkpoints.BEFORE_MIGRATE)
    recorder = MigrationRecorder(connection)
    recorder.record_applied("auth", "9999_later")
    recorder.record_applied("dbs", "9999_later")
    recorder.record_unapplied("sessions", "0001_initial")

    result = restore_backup(taken.path, passphrase(), flush=True)

    applied = set(recorder.applied_migrations())
    recorder.record_unapplied("dbs", "9999_later")
    assert ("auth", "9999_later") not in applied
    assert ("sessions", "0001_initial") in applied
    assert ("dbs", "9999_later") in applied
    assert result.migrations_unapplied == ["auth.9999_later"]
    assert result.migrations_recorded == ["sessions.0001_initial"]


def test_a_dry_run_reads_every_row_and_changes_nothing(quick):
    populated()
    taken = checkpoints.take(checkpoints.BEFORE_MIGRATE)
    User.objects.create_user("late")
    MigrationRecorder(connection).record_applied("auth", "9999_later")

    result = restore_backup(taken.path, passphrase(), flush=True, dry_run=True)

    MigrationRecorder(connection).record_unapplied("auth", "9999_later")
    assert User.objects.filter(username="late").exists()
    assert not result.schema_rebuilt and result.records_loaded == 0
    assert result.records_would_load > 0
    assert result.migrations_unapplied == ["auth.9999_later"]
    assert "auth_user" in result.tables_rebuilt


def test_a_checkpoint_needs_flush_or_no_schema(quick):
    populated()
    taken = checkpoints.take(checkpoints.BEFORE_MIGRATE)
    User.objects.filter(username="grace").delete()

    with pytest.raises(RestoreError) as refused:
        restore_backup(taken.path, passphrase())
    with pytest.raises(RestoreError):
        restore_backup(taken.path, passphrase(), dry_run=True)
    merged = restore_backup(taken.path, passphrase(), schema=False)

    assert "flush=True (--flush)" in str(refused.value)
    assert not merged.schema_rebuilt and merged.tables_rebuilt == []
    assert User.objects.filter(username="grace").exists()


def test_only_a_checkpoint_carries_a_schema(quick):
    ordinary = create_backup(passphrase(), kdf_params=FAST_KDF)

    with pytest.raises(RestoreError) as refused:
        restore_backup(ordinary, passphrase(), flush=True, schema=True)
    restored = restore_backup(ordinary, passphrase(), flush=True)

    assert "Only a checkpoint" in str(refused.value)
    assert not restored.schema_rebuilt


def test_rows_of_dbs_that_point_at_a_user_who_is_gone_let_go_or_go_too(quick):
    populated()
    taken = checkpoints.take(checkpoints.BEFORE_MIGRATE)
    late = User.objects.create_superuser("late", password="correct-horse")
    audit.record("backup.validate", actor=late, target="x.dbs", data={"ok": True})
    KnownLocation.objects.create(user=late, latitude=1.0, longitude=2.0)

    restore_backup(taken.path, passphrase(), flush=True)

    entry = AuditEvent.objects.get(action="backup.validate", target_name="x.dbs")
    assert entry.actor_id is None
    assert not KnownLocation.objects.exists()
    assert audit.verify_chain().intact


def test_the_admin_log_and_sessions_travel_too(quick):
    ada = populated()
    LogEntry.objects.create(
        user=ada,
        content_type=ContentType.objects.get_for_model(Group),
        object_id="1",
        object_repr="staff",
        action_flag=1,
    )
    taken = checkpoints.take(checkpoints.BEFORE_MIGRATE)
    LogEntry.objects.all().delete()

    restore_backup(taken.path, passphrase(), flush=True)

    assert LogEntry.objects.get().object_repr == "staff"


def test_a_checkpoint_whose_tables_no_migration_here_describes_is_refused(quick):
    foreign = container_of(
        {
            "order": ["ledger.entry"],
            "application": "tests",
            "applied": [list(key) for key in schema.applied_rows(connection)],
            "checkpoint": {"role": "before-migrate", "plan": []},
            "schema": "0" * 64,
        },
        passphrase(),
    )

    with pytest.raises(RestoreError) as refused:
        restore_backup(foreign, passphrase(), flush=True, another_application=True)

    assert "holds rows of ledger.entry" in str(refused.value)


def test_a_checkpoint_taken_with_a_migration_this_project_lacks_is_refused(quick):
    applied = [list(key) for key in schema.applied_rows(connection)]
    newer = container_of(
        {
            "order": ["auth.group"],
            "application": "tests",
            "applied": [*applied, ["auth", "9999_from_the_future"]],
            "checkpoint": {"role": "after-migrate", "plan": []},
        },
        passphrase(),
    )

    with pytest.raises(RestoreError) as refused:
        restore_backup(newer, passphrase(), flush=True, dry_run=True)

    assert "migrations this project no longer has: auth.9999_from_the_future" in str(refused.value)


def test_a_checkpoint_whose_recorded_migrations_do_not_fit_together_is_refused(quick):
    partial = container_of(
        {
            "order": ["auth.permission"],
            "application": "tests",
            "applied": [["auth", "0001_initial"]],
            "checkpoint": {"role": "before-migrate", "plan": []},
        },
        passphrase(),
    )

    with pytest.raises(RestoreError) as refused:
        restore_backup(partial, passphrase(), flush=True, dry_run=True)

    assert "do not fit together in this project" in str(refused.value)


def test_a_checkpoint_whose_tables_were_described_differently_is_refused(quick):
    applied = [list(key) for key in schema.applied_rows(connection)]
    edited = container_of(
        {
            "order": ["auth.group"],
            "application": "tests",
            "applied": applied,
            "checkpoint": {"role": "after-migrate", "plan": []},
            "schema": "f" * 64,
        },
        passphrase(),
    )

    with pytest.raises(RestoreError) as refused:
        restore_backup(edited, passphrase(), flush=True, dry_run=True)

    assert "one of them was edited since" in str(refused.value)


def test_the_restore_command_says_what_was_rebuilt(quick):
    populated()
    taken = checkpoints.take(checkpoints.BEFORE_MIGRATE)
    rehearsal, real = StringIO(), StringIO()

    call_command("dbs_restore", taken.path, "--flush", "--dry-run", stdout=rehearsal)
    call_command("dbs_restore", taken.path, "--flush", "--no-checkpoint", stdout=real)
    with pytest.raises(CommandError) as refused:
        call_command("dbs_restore", taken.path, stdout=StringIO())

    assert "tables would be rebuilt as the checkpoint's migrations describe them." in rehearsal.getvalue()
    assert "tables were rebuilt as the checkpoint's migrations describe them." in real.getvalue()
    assert "Flushed" not in real.getvalue()
    assert "Restored" in real.getvalue()
    assert "This is a checkpoint" in str(refused.value)
    entry = AuditEvent.objects.filter(action="backup.restore", status="succeeded").first()
    assert entry.data["schema"] is True and entry.data["unapplied"] == []


def test_the_state_a_database_is_in_is_read_from_its_migration_records(quick):
    found = schema.snapshot(connection)
    labels = {schema.label(model) for model in found.models}

    assert {"auth.user", "contenttypes.contenttype", "admin.logentry"} <= labels
    assert not [name for name in labels if name.startswith(("dbs.", "testapp."))]
    assert found.unknown == []
    assert schema.schema_digest(found.carried) == schema.schema_digest(list(reversed(found.carried)))
    assert "testapp.author" in schema.unmigrated_models(connection)


@pytest.mark.django_db
def test_sqlite_says_so_when_asked_to_rebuild_inside_a_transaction(quick):
    if connection.vendor != "sqlite":
        pytest.skip("Only SQLite cannot rebuild tables inside a transaction.")
    taken = checkpoints.take(checkpoints.BEFORE_MIGRATE)

    with pytest.raises(RestoreError) as refused:
        restore_backup(taken.path, passphrase(), flush=True)

    assert "cannot rebuild tables inside a transaction" in str(refused.value)
