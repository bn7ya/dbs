"""Retention in DBS_BACKUP_DIR: at most five, by recorded time, never the newest verified one."""

import datetime
import os
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from dbs import audit, schedule_runner
from dbs.container.format import write_container
from dbs.forms import BackupScheduleForm
from dbs.models import AuditEvent, BackupRecord, BackupSchedule
from dbs.naming import backup_filename, backup_stem, reserve_backup_name

MOMENT = datetime.datetime(2026, 7, 28, 2, 0, 0, tzinfo=datetime.timezone.utc)


def at(hours):
    return MOMENT + datetime.timedelta(hours=hours)


def place(directory, stem, hour, *, created_hour=None):
    name = backup_filename(stem, moment=at(hour))
    created = at(hour if created_hour is None else created_hour)
    manifest = {"created": created.isoformat(), "blocks": {"block_size": 1024}, "copy_len": 0}
    (directory / name).write_bytes(write_container(manifest, b"", b"", flags=0))
    return name


def record(directory, name, hour):
    entry = BackupRecord.objects.create(filename=name, location=str(directory / name))
    BackupRecord.objects.filter(pk=entry.pk).update(created_at=at(hour))


def verified(name, ok=True):
    if ok:
        audit.record("backup.create", target=name, data={"file": name, "verified": True})
    else:
        audit.record(
            "backup.validate", target=name, data={"file": name, "ok": False}, status=audit.FAILED
        )


def left(directory):
    return sorted(path.name for path in directory.iterdir())


@pytest.mark.django_db
def test_the_time_recorded_for_a_backup_outranks_its_name(tmp_path):
    renamed = place(tmp_path, "backup", 0)
    newer_name = place(tmp_path, "backup", 5)
    record(tmp_path, renamed, 9)

    removed = schedule_runner.keep_newest(str(tmp_path), "backup", 1)

    assert removed == [newer_name]
    assert left(tmp_path) == [renamed]
    pruned = AuditEvent.objects.get(action="backup.prune")
    assert pruned.data == {"removed": [newer_name], "keep": 1}


@pytest.mark.django_db
def test_without_a_record_the_manifest_time_orders_backups(tmp_path):
    rewritten = place(tmp_path, "backup", 0, created_hour=9)
    other = place(tmp_path, "backup", 5)

    assert schedule_runner.keep_newest(str(tmp_path), "backup", 1) == [other]
    assert left(tmp_path) == [rewritten]


@pytest.mark.django_db
def test_only_this_prefix_and_database_are_pruned(tmp_path):
    mine = [place(tmp_path, "backup", hour) for hour in range(3)]
    replica = [place(tmp_path, backup_stem("backup", "replica"), hour) for hour in range(3)]
    staging = [place(tmp_path, "staging", hour) for hour in range(3)]

    assert schedule_runner.keep_newest(str(tmp_path), "backup", 1) == mine[:2]
    assert schedule_runner.keep_newest(str(tmp_path), "backup-replica", 2) == replica[:1]
    assert left(tmp_path) == sorted([mine[2]] + replica[1:] + staging)


@pytest.mark.django_db
def test_future_names_files_that_are_not_backups_and_links_are_left_alone(tmp_path):
    kept = place(tmp_path, "backup", 0)
    future = backup_filename("backup", moment=datetime.datetime(2999, 1, 1, tzinfo=datetime.timezone.utc))
    (tmp_path / future).write_bytes((tmp_path / kept).read_bytes())
    junk = backup_filename("backup", moment=at(1))
    (tmp_path / junk).write_bytes(b"not a container")
    placeholder = backup_filename("backup", moment=at(2))
    (tmp_path / placeholder).write_bytes(b"")
    link = backup_filename("backup", moment=at(3))
    os.symlink(tmp_path / kept, tmp_path / link)
    newest = place(tmp_path, "backup", 4)

    assert schedule_runner.keep_newest(str(tmp_path), "backup", 1) == [kept]
    assert left(tmp_path) == sorted([future, junk, placeholder, link, newest])


@pytest.mark.django_db
def test_a_backup_that_failed_verification_does_not_count(tmp_path):
    older = [place(tmp_path, "backup", hour) for hour in range(2)]
    broken = place(tmp_path, "backup", 5)
    verified(broken, ok=False)

    assert schedule_runner.keep_newest(str(tmp_path), "backup", 2) == []
    assert left(tmp_path) == sorted(older + [broken])


@pytest.mark.django_db
def test_the_newest_verified_backup_survives_newer_unverified_ones(tmp_path):
    good = place(tmp_path, "backup", 0)
    verified(good)
    unverified = [place(tmp_path, "backup", hour) for hour in range(1, 4)]

    removed = schedule_runner.keep_newest(str(tmp_path), "backup", 1)

    assert removed == unverified[:2]
    assert left(tmp_path) == sorted([good, unverified[2]])


@pytest.mark.django_db
def test_two_scheduled_backups_in_one_second_both_survive(tmp_path, settings, monkeypatch):
    settings.DBS_BACKUP_DIR = str(tmp_path)
    monkeypatch.setattr(
        schedule_runner,
        "reserve_backup_name",
        lambda directory, stem: reserve_backup_name(directory, stem, at(0)),
    )
    BackupSchedule.objects.create(enabled=True, interval="6h", keep=5)

    schedule_runner.run_due(force=True)
    schedule_runner.run_due(force=True)

    assert left(tmp_path) == [
        "backup-20260728-020000Z-2.dbs",
        "backup-20260728-020000Z.dbs",
    ]
    assert all((tmp_path / name).stat().st_size > 0 for name in left(tmp_path))


@pytest.mark.django_db
def test_the_schedule_keeps_five_by_default_and_never_more(settings):
    assert BackupSchedule.load().keep == 5
    BackupSchedule.objects.all().delete()
    settings.DBS_SCHEDULE_KEEP = 14

    assert BackupSchedule.load().keep == 5


@pytest.mark.django_db
def test_the_panel_refuses_to_keep_more_than_five(settings, tmp_path):
    settings.DBS_BACKUP_DIR = str(tmp_path)
    data = {"enabled": True, "interval": "6h", "keep": 6, "database": "default"}

    form = BackupScheduleForm(data=data)

    assert not form.is_valid()
    assert "at most 5" in str(form.errors["keep"])
    assert BackupScheduleForm(data=dict(data, keep=5)).is_valid()


@pytest.mark.django_db
@pytest.mark.parametrize("flags", [["--keep", "6"], ["--keep", "0"]])
def test_dbs_schedule_refuses_a_keep_flag_outside_one_to_five(tmp_path, flags):
    with pytest.raises(CommandError) as excinfo:
        call_command("dbs_schedule", "--once", f"--output-dir={tmp_path}", *flags)

    assert "--keep" in str(excinfo.value) and "at most 5" in str(excinfo.value)
    assert not list(tmp_path.iterdir())


@pytest.mark.django_db
def test_dbs_schedule_refuses_a_keep_setting_above_five(tmp_path, settings):
    settings.DBS_SCHEDULE_KEEP = 9
    settings.DBS_BACKUP_DIR = str(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        call_command("dbs_schedule", "--once", stdout=StringIO())

    assert "DBS_SCHEDULE_KEEP" in str(excinfo.value) and "at most 5" in str(excinfo.value)
