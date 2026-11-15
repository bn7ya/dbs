"""DBS_MAX_BACKUPS: the most backups the backup folder keeps, 5 unless set, 1 to 10,000."""

import datetime
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.migrations.loader import MigrationLoader

from dbs import connection, health, schedule_runner, upgrade
from dbs.exceptions import ConfigurationError
from dbs.forms import BackupScheduleForm
from dbs.models import BackupSchedule
from dbs.naming import backup_filename
from dbs.retention import (
    KEEP_LIMIT,
    MAXIMUM_KEEP,
    bounded_keep,
    default_keep,
    maximum_keep,
    server_keep,
)
from dbs.upgrade import OK, WARN
from tests.conftest import FAST_KDF
from tests.format1 import write_container

MOMENT = datetime.datetime(2026, 7, 28, 2, 0, 0, tzinfo=datetime.timezone.utc)


def place(directory, hour):
    name = backup_filename("backup", MOMENT + datetime.timedelta(hours=hour))
    taken = MOMENT + datetime.timedelta(hours=hour)
    manifest = {"created": taken.isoformat(), "blocks": {"block_size": 1024}, "copy_len": 0}
    (directory / name).write_bytes(write_container(manifest, b"", b"", flags=0))
    return name


def test_five_is_the_limit_until_a_project_sets_another():
    assert (MAXIMUM_KEEP, KEEP_LIMIT) == (5, 10000)
    assert maximum_keep() == 5
    assert default_keep() == 5


@pytest.mark.parametrize(
    ("configured", "kept"),
    [(1, 1), (5, 5), (40, 40), (10000, 10000), ("12", 12), (0, 1), (-3, 1), (10001, 10000)],
)
def test_the_setting_is_read_within_one_and_ten_thousand(settings, configured, kept):
    settings.DBS_MAX_BACKUPS = configured

    assert maximum_keep() == kept


@pytest.mark.parametrize("configured", ["many", None, True, 2.5j])
def test_a_setting_that_is_no_number_leaves_five(settings, configured):
    settings.DBS_MAX_BACKUPS = configured

    assert maximum_keep() == 5


def test_a_lower_limit_lowers_what_is_kept_by_default(settings):
    settings.DBS_MAX_BACKUPS = 3

    assert default_keep() == 3
    assert bounded_keep(5) == 3
    assert bounded_keep("x") == 3


def test_the_server_keeps_up_to_the_limit(settings):
    settings.DBS_MAX_BACKUPS = 40

    assert server_keep(40) == 40
    with pytest.raises(ConfigurationError) as excinfo:
        server_keep(41)
    assert "at most 40" in str(excinfo.value) and "DBS_MAX_BACKUPS" in str(excinfo.value)


@pytest.mark.django_db
def test_the_schedule_is_seeded_within_the_limit(settings):
    settings.DBS_MAX_BACKUPS = 30
    settings.DBS_SCHEDULE_KEEP = 14

    assert BackupSchedule.load().keep == 14
    assert BackupSchedule.seed_keep(99) == 30


@pytest.mark.django_db
def test_a_schedule_runs_within_a_limit_lowered_after_it_was_saved(settings, tmp_path):
    settings.DBS_BACKUP_DIR = str(tmp_path)
    schedule = BackupSchedule.objects.create(enabled=True, interval="6h", keep=5)
    settings.DBS_MAX_BACKUPS = 2

    assert schedule_runner.schedule_plan(schedule)["keep"] == 2


@pytest.mark.django_db
def test_the_panel_takes_a_keep_up_to_the_limit(settings, tmp_path):
    settings.DBS_BACKUP_DIR = str(tmp_path)
    settings.DBS_MAX_BACKUPS = 12
    data = {"enabled": True, "interval": "6h", "keep": 12, "database": "default"}

    form = BackupScheduleForm(data=data)
    beyond = BackupScheduleForm(data=dict(data, keep=13))

    assert form.is_valid(), form.errors
    assert "at most 12" in form.fields["keep"].help_text
    assert not beyond.is_valid()
    assert "at most 12" in str(beyond.errors["keep"])


@pytest.mark.django_db
def test_the_panel_never_takes_more_than_ten_thousand(settings, tmp_path):
    settings.DBS_BACKUP_DIR = str(tmp_path)
    settings.DBS_MAX_BACKUPS = 10000
    data = {"enabled": True, "interval": "6h", "keep": 10000, "database": "default"}

    assert BackupScheduleForm(data=data).is_valid()
    assert not BackupScheduleForm(data=dict(data, keep=10001)).is_valid()


@pytest.mark.django_db
def test_dbs_schedule_keeps_up_to_the_limit(settings, tmp_path, fast_kdf):
    settings.DBS_MAX_BACKUPS = 8

    call_command(
        "dbs_schedule", "--once", f"--output-dir={tmp_path}", "--keep", "8", stdout=StringIO()
    )
    with pytest.raises(CommandError) as excinfo:
        call_command("dbs_schedule", "--once", f"--output-dir={tmp_path}", "--keep", "9")

    assert "at most 8" in str(excinfo.value)
    assert len(list(tmp_path.glob("*.dbs"))) == 1


@pytest.mark.django_db
@pytest.mark.parametrize(("limit", "left"), [(None, 5), (2, 2), (9, 8)])
def test_a_streamed_backup_prunes_its_folder_to_the_limit(settings, tmp_path, limit, left):
    if limit is not None:
        settings.DBS_MAX_BACKUPS = limit
    older = [place(tmp_path, hour) for hour in range(7)]
    written = place(tmp_path, 9)

    schedule_runner.keep_at_most(str(tmp_path), "backup", maximum_keep(), written)

    kept = sorted(path.name for path in tmp_path.glob("*.dbs"))
    assert len(kept) == left
    assert written in kept
    assert kept == sorted((older + [written])[-left:])


@pytest.mark.django_db
def test_the_stream_command_reads_the_limit(settings, tmp_path, monkeypatch, fast_kdf):
    from dbs.management.commands import dbs_backup

    settings.DBS_MAX_BACKUPS = 7
    seen = []
    monkeypatch.setattr(
        dbs_backup, "keep_at_most", lambda directory, prefix, keep, written: seen.append(keep)
    )

    class Output(StringIO):
        def __init__(self):
            super().__init__()
            self.buffer = open(tmp_path / "streamed", "wb")

    out = Output()
    try:
        call_command(
            "dbs_backup", "--stream", f"--output-dir={tmp_path / 'kept'}",
            "--passphrase", "stream-passphrase", "--kdf-time", str(FAST_KDF.time_cost),
            "--kdf-memory", str(FAST_KDF.memory_cost), stdout=out, stderr=StringIO(),
        )
    finally:
        out.buffer.close()

    assert seen == [7]


@pytest.mark.django_db
def test_health_and_connection_details_name_the_limit(settings):
    settings.DBS_MAX_BACKUPS = 25

    assert health.report().as_dict()["schedule"]["max_backups"] == 25
    assert connection.details()["max_backups"] == 25


def test_upgrade_says_what_the_limit_is(settings):
    unset = upgrade.MaximumBackups().check()
    settings.DBS_MAX_BACKUPS = 60
    raised = upgrade.MaximumBackups().check()

    assert unset.level == OK and "at most 5" in unset.message
    assert raised.level == OK and "at most 60" in raised.message
    assert upgrade.MaximumBackups in upgrade.STEPS


@pytest.mark.parametrize("configured", [0, 10001, "many", True])
def test_upgrade_reports_a_limit_that_cannot_be_used(settings, configured):
    settings.DBS_MAX_BACKUPS = configured

    finding = upgrade.MaximumBackups().check()

    assert finding.level == WARN
    assert repr(configured) in finding.message
    assert finding.remedy == "DBS_MAX_BACKUPS = 5"


@pytest.mark.django_db
def test_upgrade_measures_the_schedule_against_the_limit(settings):
    settings.DBS_MAX_BACKUPS = 20
    settings.DBS_SCHEDULE_KEEP = 14

    assert upgrade.KeepAtMostFive().check().level == OK

    settings.DBS_SCHEDULE_KEEP = 21
    finding = upgrade.KeepAtMostFive().check()

    assert finding.level == WARN and "at most 20" in finding.message


def test_the_schedule_table_takes_a_keep_up_to_ten_thousand():
    loader = MigrationLoader(None)
    assert ("dbs", "0006_max_backups") in loader.disk_migrations
    validators = BackupSchedule._meta.get_field("keep").validators

    assert [validator.limit_value for validator in validators] == [1, 10000]
