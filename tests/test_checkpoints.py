"""A checkpoint: what it holds, how it is named, kept, recorded and listed."""

import datetime
import json
import os
from io import StringIO

import pytest
from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.db import connections

from dbs import audit, checkpoints, health, schedule_runner
from dbs.engine import schema, validate_backup
from dbs.models import AuditEvent, BackupRecord
from dbs.naming import backup_filename
from tests.format1 import write_container
from tests.payloads import header_of, read_payload

MOMENT = datetime.datetime(2026, 7, 28, 2, 0, 0, tzinfo=datetime.timezone.utc)


@pytest.fixture(autouse=True)
def quick(settings, tmp_path):
    settings.DBS_BACKUP_DIR = str(tmp_path / "backups")
    settings.DBS_KDF_TIME_COST = 1
    settings.DBS_KDF_MEMORY_COST = 8 * 1024
    settings.DBS_KDF_PARALLELISM = 1
    return tmp_path / "backups"


def passphrase():
    return schedule_runner.unattended_passphrase()


def names(folder):
    return sorted(path.name for path in folder.glob("*.dbs"))


def place(folder, stem, hour):
    folder.mkdir(exist_ok=True)
    name = backup_filename(stem, MOMENT + datetime.timedelta(hours=hour))
    taken = MOMENT + datetime.timedelta(hours=hour)
    manifest = {"created": taken.isoformat(), "blocks": {"block_size": 1024}, "copy_len": 0}
    (folder / name).write_bytes(write_container(manifest, b"", b"", flags=0))
    return name


@pytest.mark.django_db
def test_a_checkpoint_holds_what_migrations_manage_and_nothing_dbs_keeps_for_itself(quick):
    User.objects.create_user("ada")
    audit.record("backup.validate", target="x.dbs", data={"ok": True})

    taken = checkpoints.take(checkpoints.BEFORE_MIGRATE, plan=["shop.0002_x"])

    header = header_of(taken.path, passphrase())
    held = set(header["order"])
    assert {
        "auth.user",
        "auth.group",
        "auth.permission",
        "contenttypes.contenttype",
        "sessions.session",
        "admin.logentry",
    } <= held
    assert not [label for label in held if label.startswith("dbs.")]
    assert not [label for label in held if label.startswith("testapp.")]
    records = read_payload(taken.path, passphrase()).records
    assert [record["fields"]["username"] for record in records if record["model"] == "auth.user"] == ["ada"]


@pytest.mark.django_db
def test_a_checkpoint_records_every_applied_migration_and_what_it_stands_before(quick):
    taken = checkpoints.take(checkpoints.BEFORE_MIGRATE, plan=["shop.0002_x", "-shop.0001_y"])

    header = header_of(taken.path, passphrase())
    applied = [tuple(row) for row in header["applied"]]
    assert ("auth", "0001_initial") in applied and ("dbs", "0006_max_backups") in applied
    assert applied == schema.applied_rows(connections["default"])
    assert header["checkpoint"] == {
        "role": "before-migrate",
        "plan": ["shop.0002_x", "-shop.0001_y"],
    }
    assert len(header["schema"]) == 64
    assert header["application"] == "tests"
    assert header["migrations"]["auth"]


@pytest.mark.django_db
def test_a_checkpoint_holds_no_files(quick, settings, tmp_path):
    kept = tmp_path / "kept"
    kept.mkdir()
    (kept / "a.txt").write_text("a file")
    settings.DBS_FILE_ROOTS = [str(kept)]

    taken = checkpoints.take(checkpoints.AFTER_MIGRATE)

    assert read_payload(taken.path, passphrase()).files == []


@pytest.mark.django_db
def test_a_model_a_project_leaves_out_of_backups_is_left_out_of_checkpoints(quick, settings):
    settings.DBS_EXCLUDE_MODELS = ["auth.Group", "-sessions.session"]

    taken = checkpoints.take(checkpoints.BEFORE_MIGRATE)

    held = header_of(taken.path, passphrase())["order"]
    assert "auth.group" not in held
    assert "sessions.session" in held and "auth.user" in held


@pytest.mark.django_db
def test_parents_come_before_what_refers_to_them(quick):
    held = header_of(checkpoints.take(checkpoints.BEFORE_MIGRATE).path, passphrase())["order"]

    assert held.index("contenttypes.contenttype") < held.index("auth.permission")
    assert held.index("auth.user") < held.index("admin.logentry")


def test_a_checkpoint_is_named_after_what_it_stands_beside(settings):
    assert checkpoints.stem("before-migrate", "default") == "backup-before-migrate"
    assert checkpoints.stem("after-restore", "secondary") == "backup-secondary-after-restore"

    settings.DBS_BACKUP_PREFIX = "shop"

    assert checkpoints.stem("after-migrate", "default") == "shop-after-migrate"
    assert checkpoints.role_of("shop-after-migrate-20260728-020000Z.dbs", "default") == "after-migrate"
    assert checkpoints.role_of("shop-20260728-020000Z.dbs", "default") is None
    assert checkpoints.role_of("shop-after-migrate-20260728-020000Z.dbs", "secondary") is None


@pytest.mark.django_db
def test_a_checkpoint_is_verified_recorded_and_audited_as_one(quick):
    taken = checkpoints.take(checkpoints.BEFORE_MIGRATE, plan=["shop.0002_x"])

    entry = AuditEvent.objects.get(action="backup.checkpoint")
    record = BackupRecord.objects.get(filename=taken.name)
    assert (entry.status, entry.target_name) == ("succeeded", taken.name)
    assert entry.data["role"] == "before-migrate"
    assert entry.data["migrations"] == ["shop.0002_x"]
    assert entry.data["verified"] is True and entry.data["size"] == os.path.getsize(taken.path)
    assert record.note == "Checkpoint before a migrate: shop.0002_x"
    assert record.location == taken.path
    assert validate_backup(taken.path, passphrase()).ok


@pytest.mark.django_db
def test_a_checkpoint_is_not_the_last_backup_health_reports(quick):
    checkpoints.take(checkpoints.BEFORE_MIGRATE)

    report = health.report()

    assert report.last_backup_at is None
    assert not AuditEvent.objects.filter(action="backup.create").exists()


@pytest.mark.django_db
def test_validation_says_what_a_checkpoint_stands_beside(quick):
    taken = checkpoints.take(checkpoints.AFTER_RESTORE)

    result = validate_backup(taken.path, passphrase())

    assert result.checkpoint == {"role": "after-restore", "plan": []}
    assert "Checkpoint after a restore" in result.summary()


@pytest.mark.django_db
def test_checkpoints_beyond_the_limit_go_oldest_first(quick, settings):
    settings.DBS_MAX_BACKUPS = 3
    old = [
        place(quick, "backup-before-migrate", 0),
        place(quick, "backup-after-migrate", 1),
        place(quick, "backup-before-restore", 2),
    ]

    taken = checkpoints.take(checkpoints.AFTER_RESTORE)

    assert names(quick) == sorted([old[1], old[2], taken.name])
    pruned = AuditEvent.objects.get(action="backup.prune")
    assert pruned.data == {"removed": [old[0]], "keep": 3}


@pytest.mark.django_db
def test_the_newest_before_and_after_stay_even_under_a_limit_of_one(quick, settings):
    settings.DBS_MAX_BACKUPS = 1
    older = [place(quick, "backup-before-migrate", 0), place(quick, "backup-after-migrate", 1)]
    before = place(quick, "backup-before-migrate", 5)

    after = checkpoints.take(checkpoints.AFTER_MIGRATE)

    assert names(quick) == sorted([before, after.name])
    assert not set(older) & set(names(quick))


@pytest.mark.django_db
def test_a_file_named_to_be_kept_is_never_pruned(quick, settings):
    settings.DBS_MAX_BACKUPS = 1
    restoring = place(quick, "backup-before-migrate", 0)

    checkpoints.take(checkpoints.BEFORE_RESTORE, protect=(restoring,))
    checkpoints.take(checkpoints.AFTER_RESTORE, protect=(restoring,))

    assert restoring in names(quick)


@pytest.mark.django_db
def test_checkpoints_never_prune_a_backup_that_is_not_one(quick, settings):
    settings.DBS_MAX_BACKUPS = 1
    scheduled = [place(quick, "backup", hour) for hour in range(4)]
    other = place(quick, "backup-secondary-before-migrate", 0)

    checkpoints.take(checkpoints.BEFORE_MIGRATE)
    checkpoints.take(checkpoints.AFTER_MIGRATE)

    assert set(scheduled) <= set(names(quick))
    assert other in names(quick)


@pytest.mark.django_db
def test_scheduled_retention_never_prunes_a_checkpoint(quick):
    taken = checkpoints.take(checkpoints.BEFORE_MIGRATE)
    scheduled = [place(quick, "backup", hour) for hour in range(4)]

    schedule_runner.keep_newest(str(quick), "backup", 1)

    assert names(quick) == sorted([taken.name, scheduled[-1]])


@pytest.mark.django_db
def test_the_list_names_each_checkpoint_with_what_it_stands_beside(quick):
    before = checkpoints.take(checkpoints.BEFORE_MIGRATE, plan=["shop.0002_x"])
    after = checkpoints.take(checkpoints.AFTER_MIGRATE, plan=["shop.0002_x"])
    unrecorded = place(quick, "backup-before-restore", 0)
    place(quick, "backup", 1)

    listed = checkpoints.listing(["default"])

    assert [entry["name"] for entry in listed] == [unrecorded, before.name, after.name]
    assert [entry["role"] for entry in listed] == ["before-restore", "before-migrate", "after-migrate"]
    assert [entry["migrations"] for entry in listed] == [None, ["shop.0002_x"], ["shop.0002_x"]]
    assert listed[1]["path"] == before.path and listed[1]["size"] == before.size


@pytest.mark.django_db
def test_the_command_lists_checkpoints_as_text_and_json(quick):
    out = StringIO()
    call_command("dbs", "checkpoints", stdout=out)
    taken = checkpoints.take(checkpoints.BEFORE_MIGRATE, plan=["shop.0002_x"])
    text, data = StringIO(), StringIO()

    call_command("dbs", "checkpoints", stdout=text)
    call_command("dbs_checkpoints", "--json", "--database", "default", stdout=data)

    assert "No checkpoints in" in out.getvalue()
    assert "before a migrate: shop.0002_x" in text.getvalue()
    assert taken.path in text.getvalue()
    assert [entry["name"] for entry in json.loads(data.getvalue())] == [taken.name]


@pytest.mark.django_db
def test_the_command_says_when_there_is_nowhere_to_keep_checkpoints(settings):
    settings.DBS_BACKUP_DIR = None
    out, data = StringIO(), StringIO()

    call_command("dbs", "checkpoints", stdout=out)
    call_command("dbs", "checkpoints", "--json", stdout=data)

    assert "DBS_BACKUP_DIR is not set" in out.getvalue()
    assert json.loads(data.getvalue()) == []


@pytest.mark.django_db
def test_a_checkpoint_needs_a_folder_and_a_passphrase(settings, monkeypatch):
    settings.DBS_BACKUP_DIR = None
    with pytest.raises(checkpoints.CheckpointError) as nowhere:
        checkpoints.take(checkpoints.BEFORE_MIGRATE)

    settings.DBS_BACKUP_DIR = "/tmp/anywhere"
    monkeypatch.setattr(schedule_runner, "unattended_passphrase", lambda: None)
    with pytest.raises(checkpoints.CheckpointError) as unencrypted:
        checkpoints.take(checkpoints.BEFORE_MIGRATE)

    assert "DBS_BACKUP_DIR is not set" in str(nowhere.value)
    assert "SECRET_KEY or DBS_PASSPHRASE" in str(unencrypted.value)


@pytest.mark.django_db
def test_a_checkpoint_that_fails_leaves_no_file_and_a_failed_audit_row(quick, monkeypatch):
    from dbs.engine import backup

    def broken(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(backup, "write_selection", broken)

    with pytest.raises(OSError):
        checkpoints.take(checkpoints.BEFORE_MIGRATE)

    assert names(quick) == []
    entry = AuditEvent.objects.get(action="backup.checkpoint")
    assert (entry.status, entry.error_code) == ("failed", audit.DISK_FULL)


@pytest.mark.django_db
def test_a_project_whose_dbs_tables_are_not_there_yet_still_gets_its_checkpoint(
    quick, monkeypatch
):
    from django.db import DatabaseError

    def missing(*args, **kwargs):
        raise DatabaseError("no such table: dbs_backuprecord")

    monkeypatch.setattr(schedule_runner, "stored_backups", missing)
    monkeypatch.setattr(audit, "record", missing)

    taken = checkpoints.take(checkpoints.BEFORE_MIGRATE)

    assert names(quick) == [taken.name]


@pytest.mark.parametrize(
    ("described", "is_test"),
    [
        ({"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}, True),
        ({"ENGINE": "django.db.backends.sqlite3", "NAME": "file:memorydb_default?mode=memory&cache=shared"}, True),
        ({"ENGINE": "django.db.backends.sqlite3", "NAME": "/srv/app/db.sqlite3"}, False),
        ({"ENGINE": "django.db.backends.sqlite3", "NAME": "/srv/app/test_db.sqlite3"}, True),
        ({"ENGINE": "django.db.backends.postgresql", "NAME": "shop"}, False),
        ({"ENGINE": "django.db.backends.postgresql", "NAME": "test_shop"}, True),
        ({"ENGINE": "django.db.backends.postgresql", "NAME": "shop_ci", "TEST": {"NAME": "shop_ci"}}, True),
    ],
)
def test_a_test_database_is_told_from_a_real_one(described, is_test):
    class Connection:
        vendor = "sqlite" if "sqlite" in described["ENGINE"] else "postgresql"
        settings_dict = described

    assert checkpoints.is_test_database(Connection()) is is_test


@pytest.mark.django_db
def test_readiness_names_what_stands_in_the_way(quick, settings, monkeypatch, tmp_path):
    assert checkpoints.readiness().problems == []

    blocker = tmp_path / "a-file"
    blocker.write_text("x")
    settings.DBS_BACKUP_DIR = str(blocker / "backups")
    monkeypatch.setattr(schedule_runner, "unattended_passphrase", lambda: None)

    problems = checkpoints.readiness().problems

    assert any("is not a folder this process can write into" in problem for problem in problems)
    assert any("no passphrase encrypts a checkpoint" in problem for problem in problems)


@pytest.mark.django_db
def test_readiness_counts_the_room_two_checkpoints_need(quick, monkeypatch):
    import shutil
    from collections import namedtuple

    taken = checkpoints.take(checkpoints.BEFORE_MIGRATE)
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda path: Usage(10**9, 10**9 - 1000, taken.size))

    found = checkpoints.readiness()

    assert any("less than the two checkpoints a migration writes" in problem for problem in found.problems)


@pytest.mark.django_db
def test_groups_and_their_members_travel_in_a_checkpoint(quick):
    staff = Group.objects.create(name="staff")
    User.objects.create_user("ada").groups.add(staff)

    taken = checkpoints.take(checkpoints.BEFORE_MIGRATE)

    records = read_payload(taken.path, passphrase()).records
    ada = next(record for record in records if record["model"] == "auth.user")
    assert ada["fields"]["groups"] == [staff.pk]
    assert ada["pk"] is not None and "password" in ada["fields"]
