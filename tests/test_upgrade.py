"""`manage.py dbs upgrade`: the checks, the fixes, and the refusal to lose backups."""

from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from dbs import upgrade
from dbs.container.format import (
    FORMAT_VERSION,
    SEALED_PREFIX,
    container_version,
    copy_offsets,
    seal_header,
)
from dbs.engine import create_backup
from dbs.keys import default_passphrase
from dbs.upgrade import ACTION, FIXED, OK, WARN, Converter
from tests.testapp.models import Author

OFFLINE = {"offline": True}


def run(**options):
    out = StringIO()
    call_command("dbs", "upgrade", stdout=out, stderr=StringIO(), **dict(OFFLINE, **options))
    return out.getvalue()


def levels(report):
    return {finding.step: finding.level for finding in report.findings}


def as_version(current: bytes, version: int) -> bytes:
    if version == FORMAT_VERSION:
        return current
    return seal_header(version, b"") + current


def unwrap(data: bytes) -> bytes:
    _magic, version, length = SEALED_PREFIX.unpack_from(data)
    return data if version == FORMAT_VERSION else data[length:]


def stamp_version(source: Path, destination: Path, version: int):
    destination.write_bytes(as_version(source.read_bytes(), version))
    return destination


def restamp(version):
    def convert(data, passphrase):
        return as_version(unwrap(data), version)

    return Converter(produces=version, convert=convert)


@pytest.fixture
def backups(tmp_path, db):
    Author.objects.create(name="Ada")
    directory = tmp_path / "backups"
    directory.mkdir()
    (directory / "current.dbs").write_bytes(create_backup(default_passphrase()))
    return directory


@pytest.fixture(autouse=True)
def empty_converters(monkeypatch):
    monkeypatch.setattr(upgrade, "CONVERTERS", {})


@pytest.mark.django_db
def test_a_correctly_configured_project_is_up_to_date():
    report = upgrade.run_steps(apply_fixes=False)

    assert not report.blocked
    assert levels(report)["installed app"] == OK
    assert levels(report)["session guard"] == OK
    assert levels(report)["passphrase"] == OK
    assert "up to date" in run()


@pytest.mark.django_db
def test_the_models_and_their_migrations_agree():
    call_command("makemigrations", "dbs", "--check", "--dry-run", verbosity=0)


@pytest.mark.django_db(transaction=True)
def test_an_unapplied_dbs_migration_is_reported_and_applied():
    call_command("migrate", "dbs", "0001", verbosity=0)
    try:
        step = upgrade.Migrations()

        reported = step.check()
        applied = step.fix()

        assert reported.level == ACTION
        assert reported.remedy == "python manage.py migrate dbs"
        assert applied.level == FIXED
        assert step.check().level == OK
    finally:
        call_command("migrate", "dbs", verbosity=0)


@pytest.mark.django_db(transaction=True)
def test_the_audit_trail_step_applies_its_migration():
    call_command("migrate", "dbs", "0002", verbosity=0)
    try:
        step = upgrade.AuditTrail()

        reported = step.check()
        applied = step.fix()

        assert reported.level == ACTION
        assert reported.remedy == "python manage.py migrate dbs"
        assert applied.level == FIXED
        assert step.check().level == OK
    finally:
        call_command("migrate", "dbs", verbosity=0)


@pytest.mark.django_db
def test_a_schedule_left_in_settings_points_at_the_panel(settings):
    settings.DBS_SCHEDULE_INTERVAL = "6h"

    finding = upgrade.ScheduleInDatabase().check()

    assert finding.level == WARN
    assert "/admin/dbs/backupschedule/" in finding.remedy


@pytest.mark.django_db
def test_an_enabled_schedule_is_reported_as_current(settings):
    from dbs.models import BackupSchedule

    settings.DBS_SCHEDULE_INTERVAL = "6h"
    BackupSchedule.objects.create(enabled=True, interval="6h")

    assert upgrade.ScheduleInDatabase().check().level == OK


@pytest.mark.django_db
def test_the_schedule_command_with_the_panel_off_is_reported(settings):
    from dbs.models import BackupSchedule

    settings.DBS_SCHEDULER = "command"
    BackupSchedule.objects.create(enabled=False, interval="6h")

    finding = upgrade.ScheduleInDatabase().check()

    assert finding.level == WARN
    assert "/admin/dbs/backupschedule/" in finding.remedy
    assert "--interval" in finding.remedy


@pytest.mark.django_db
def test_the_panel_off_in_thread_mode_is_fine(settings):
    from dbs.models import BackupSchedule

    settings.DBS_SCHEDULER = "thread"
    BackupSchedule.objects.create(enabled=False, interval="6h")

    assert upgrade.ScheduleInDatabase().check().level == OK


def test_a_missing_backup_directory_is_reported(settings):
    settings.DBS_BACKUP_DIR = None

    finding = upgrade.BackupDirectory().check()

    assert finding.level == WARN
    assert "DBS_BACKUP_DIR" in finding.remedy


def test_a_backup_directory_is_fine(settings, tmp_path):
    settings.DBS_BACKUP_DIR = str(tmp_path)

    assert upgrade.BackupDirectory().check().level == OK


def test_a_backup_directory_this_user_cannot_create_is_reported(settings, tmp_path):
    blocker = tmp_path / "a-file"
    blocker.write_text("not a folder")
    settings.DBS_BACKUP_DIR = str(blocker / "backups")

    finding = upgrade.BackupDirectory().check()

    assert finding.level == WARN
    assert "not writable" in finding.message


def test_a_backup_directory_that_does_not_exist_yet_is_fine(settings, tmp_path):
    settings.DBS_BACKUP_DIR = str(tmp_path / "nested" / "backups")

    assert upgrade.BackupDirectory().check().level == OK


def test_an_unknown_scheduler_mode_blocks(settings):
    settings.DBS_SCHEDULER = "cron"

    assert upgrade.SchedulerMode().check().level == ACTION


def test_a_known_scheduler_mode_is_fine(settings):
    settings.DBS_SCHEDULER = "command"

    assert upgrade.SchedulerMode().check().level == OK


@pytest.mark.django_db
def test_a_missing_guard_middleware_is_reported(settings):
    settings.MIDDLEWARE = [
        m for m in settings.MIDDLEWARE if "DBSSecurityMiddleware" not in m
    ]

    report = upgrade.run_steps(apply_fixes=False)

    assert levels(report)["session guard"] == WARN
    assert "scoring requests" in run()


@pytest.mark.django_db
def test_the_guard_is_not_demanded_without_the_admin(settings):
    settings.MIDDLEWARE = [
        m for m in settings.MIDDLEWARE if "DBSSecurityMiddleware" not in m
    ]
    settings.INSTALLED_APPS = [
        app for app in settings.INSTALLED_APPS if app != "django.contrib.admin"
    ]

    report = upgrade.run_steps(apply_fixes=False)

    assert levels(report)["session guard"] == OK
    assert levels(report)["admin panel"] == WARN


@pytest.mark.django_db
def test_pre_022_exclude_semantics_are_caught(settings):
    settings.DBS_EXCLUDE_MODELS = ["contenttypes.contenttype", "myapp.Thing"]

    report = upgrade.run_steps(apply_fixes=False)

    assert levels(report)["excluded models"] == WARN
    printed = run()
    assert "contenttypes.contenttype" in printed
    assert "extends them" in printed


@pytest.mark.django_db
def test_a_deliberate_re_inclusion_is_not_flagged(settings):
    settings.DBS_EXCLUDE_MODELS = ["-sessions.Session"]

    assert levels(upgrade.run_steps(apply_fixes=False))["excluded models"] == OK


@pytest.mark.django_db
def test_a_project_with_no_derivable_passphrase_is_blocked(settings, monkeypatch):
    monkeypatch.delenv("DBS_PASSPHRASE", raising=False)
    settings.SECRET_KEY = ""
    settings.SECRET_KEY_FALLBACKS = []

    report = upgrade.run_steps(apply_fixes=False)

    assert levels(report)["passphrase"] == ACTION
    assert report.blocked


@pytest.mark.django_db
def test_empty_restore_roots_are_reported(settings):
    settings.DBS_FILE_ROOTS = ["/srv/uploads"]
    settings.DBS_RESTORE_ROOTS = []

    assert levels(upgrade.run_steps(apply_fixes=False))["restore roots"] == WARN


@pytest.mark.django_db
def test_check_changes_nothing_and_reports(settings):
    settings.DBS_EXCLUDE_MODELS = ["auth.permission"]

    printed = run(check=True)

    assert "excluded models" in printed


@pytest.mark.django_db
def test_check_exits_non_zero_when_an_action_is_outstanding(settings, monkeypatch):
    monkeypatch.delenv("DBS_PASSPHRASE", raising=False)
    settings.SECRET_KEY = ""
    settings.SECRET_KEY_FALLBACKS = []

    with pytest.raises(CommandError):
        run(check=True)


@pytest.mark.django_db
def test_the_ai_step_repairs_a_hand_edited_skill(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    call_command("dbs", "ai", root=str(tmp_path), stdout=StringIO())
    skill = tmp_path / ".claude" / "skills" / "django-dbs" / "SKILL.md"
    skill.write_text("edited by hand")

    step = upgrade.AiInstructions()
    assert step.check().level == ACTION

    step.fix()
    assert step.check().level == OK
    assert "edited by hand" not in skill.read_text()


def test_self_update_refuses_on_a_source_checkout():
    assert upgrade.is_editable_install() is True


def test_version_comparison():
    assert upgrade.is_newer("1.0.0", "0.9.9")
    assert upgrade.is_newer("0.3.10", "0.3.9")
    assert not upgrade.is_newer("0.3.1", "0.3.1")
    assert not upgrade.is_newer("0.2.2", "0.3.0")


@pytest.mark.django_db
def test_current_backups_need_no_conversion(backups):
    printed = run(backups=str(backups))

    assert f"all at format version {FORMAT_VERSION}" in printed


@pytest.mark.django_db
def test_an_empty_directory_is_fine(tmp_path):
    empty = tmp_path / "none"
    empty.mkdir()

    assert "no .dbs files" in run(backups=str(empty))


@pytest.mark.django_db
def test_an_unconvertible_backup_blocks_and_touches_nothing(backups):
    future = stamp_version(backups / "current.dbs", backups / "future.dbs", 2)
    before = {path: path.read_bytes() for path in backups.iterdir()}

    with pytest.raises(CommandError, match="cannot be read"):
        run(backups=str(backups))

    assert {path: path.read_bytes() for path in backups.iterdir()} == before
    assert future.exists()


@pytest.mark.django_db
def test_an_unconvertible_backup_blocks_check_too(backups):
    stamp_version(backups / "current.dbs", backups / "future.dbs", 2)

    with pytest.raises(CommandError, match="not readable"):
        run(backups=str(backups), check=True)


@pytest.mark.django_db
def test_a_registered_converter_rewrites_and_keeps_the_original(backups, monkeypatch):
    source = stamp_version(backups / "current.dbs", backups / "old.dbs", 2)
    original = source.read_bytes()
    monkeypatch.setattr(upgrade, "CONVERTERS", {2: restamp(FORMAT_VERSION)})

    printed = run(backups=str(backups))

    assert "original is untouched" in printed
    assert source.read_bytes() == original
    converted = backups / "old.dbs.converted"
    assert converted.is_file()
    assert container_version(converted.read_bytes()) == FORMAT_VERSION


@pytest.mark.django_db
def test_conversion_chains_across_several_versions(backups, monkeypatch):
    source = stamp_version(backups / "current.dbs", backups / "ancient.dbs", 3)
    monkeypatch.setattr(upgrade, "CONVERTERS", {3: restamp(2), 2: restamp(FORMAT_VERSION)})

    run(backups=str(backups))

    converted = backups / "ancient.dbs.converted"
    assert container_version(converted.read_bytes()) == FORMAT_VERSION
    assert container_version(source.read_bytes()) == 3


@pytest.mark.django_db
def test_a_converter_that_destroys_the_payload_beyond_repair_is_caught(backups, monkeypatch):
    stamp_version(backups / "current.dbs", backups / "old.dbs", 2)

    def wreck(data, passphrase):
        current = unwrap(data)
        copies_start, copy_b_offset, copy_len = copy_offsets(current)
        patched = bytearray(current)
        copies_end = copy_b_offset + copy_len
        patched[copies_start:copies_end] = bytes(copies_end - copies_start)
        return bytes(patched)

    monkeypatch.setattr(
        upgrade, "CONVERTERS", {2: Converter(produces=FORMAT_VERSION, convert=wreck)}
    )

    with pytest.raises(CommandError, match="cannot be read"):
        run(backups=str(backups))

    assert not (backups / "old.dbs.converted").exists()


@pytest.mark.django_db
def test_a_converter_that_raises_is_reported_not_propagated(backups, monkeypatch):
    stamp_version(backups / "current.dbs", backups / "old.dbs", 2)

    def explode(data, passphrase):
        raise ValueError("no")

    monkeypatch.setattr(
        upgrade, "CONVERTERS", {2: Converter(produces=FORMAT_VERSION, convert=explode)}
    )

    with pytest.raises(CommandError, match="cannot be read"):
        run(backups=str(backups))


@pytest.mark.django_db
def test_a_file_that_is_not_a_container_is_reported(backups):
    (backups / "junk.dbs").write_bytes(b"not a container at all")

    with pytest.raises(CommandError, match="cannot be read"):
        run(backups=str(backups))


def test_abandonment_needs_a_terminal_and_the_exact_phrase():
    class NotATerminal:
        def isatty(self):
            return False

    assert upgrade.confirm_abandonment(1, NotATerminal()) is False
    assert upgrade.abandonment_phrase(1) == "abandon 1 backup"
    assert upgrade.abandonment_phrase(4) == "abandon 4 backups"


def test_there_is_no_flag_that_skips_the_confirmation():
    from dbs.management.commands import dbs_upgrade

    source = Path(dbs_upgrade.__file__).read_text()
    for bypass in ("--force", "--abandon", "--no-input", "--noinput"):
        assert bypass not in source


def test_nothing_in_the_command_deletes_a_backup():
    from dbs.management.commands import dbs_upgrade

    source = Path(dbs_upgrade.__file__).read_text() + Path(upgrade.__file__).read_text()
    for destructive in ("unlink(", "rmtree(", "os.remove(", "shutil.move("):
        assert destructive not in source


def test_every_command_name_reaches_the_upgrade_command():
    from django.core.management import get_commands, load_command_class

    commands = get_commands()
    for name in ("dbs_upgrade", "dbs-upgrade"):
        assert commands[name] == "dbs", name
    assert load_command_class("dbs", "dbs-upgrade").__module__.endswith("dbs_upgrade")


def test_the_umbrella_lists_upgrade():
    from dbs.management.commands.dbs import SUBCOMMANDS

    assert SUBCOMMANDS["upgrade"][0] == "dbs_upgrade"
    out = StringIO()
    call_command("dbs", stdout=out)
    assert "manage.py dbs upgrade" in out.getvalue()


@pytest.mark.django_db
def test_models_whose_default_manager_hides_rows_are_named(monkeypatch):
    from dbs.registry import BackupRegistry
    from tests.softdeleteapp.models import Category, Item

    registry = BackupRegistry()
    for model in (Author, Category, Item):
        registry.register(model)
    monkeypatch.setattr("dbs.registry.backup_registry", registry)

    finding = next(
        f for f in upgrade.run_steps(apply_fixes=False).findings if f.step == "hidden rows"
    )

    assert finding.level == OK
    assert "softdeleteapp.category" in finding.message
    assert "softdeleteapp.item" in finding.message
    assert "testapp.author" not in finding.message


@pytest.mark.django_db
def test_a_custom_get_queryset_is_left_alone(monkeypatch):
    from dbs import ModelBackup
    from dbs.registry import BackupRegistry
    from tests.softdeleteapp.models import Category

    class LiveOnly(ModelBackup):
        def get_queryset(self, model):
            return model._default_manager.all()

    registry = BackupRegistry()
    registry.register(Category)(LiveOnly)
    monkeypatch.setattr("dbs.registry.backup_registry", registry)

    finding = next(
        f for f in upgrade.run_steps(apply_fixes=False).findings if f.step == "hidden rows"
    )

    assert finding.message == "no backed-up model has a default manager that hides rows"


def test_the_dependencies_step_checks_what_the_manager_needs():
    finding = upgrade.Dependencies().check()

    assert finding.level == OK
    assert "waitress" in finding.message and "rest_framework" in finding.message


def test_a_missing_manager_dependency_is_reported(monkeypatch):
    import importlib

    real_import = importlib.import_module

    def without_waitress(name, *args, **kwargs):
        if name == "waitress":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", without_waitress)

    finding = upgrade.Dependencies().check()

    assert finding.level == ACTION
    assert "waitress" in finding.message and "paramiko" not in finding.message
    assert "django-dbs>=0.5" in finding.remedy


def _finding(step):
    return next(f for f in upgrade.run_steps(apply_fixes=False).findings if f.step == step)


@pytest.mark.django_db
def test_unmanaged_models_left_out_by_discovery_are_named(monkeypatch):
    from dbs.registry import BackupRegistry

    monkeypatch.setattr("dbs.registry.backup_registry", BackupRegistry())

    finding = _finding("unmanaged models")

    assert finding.level == OK
    assert finding.since == "0.7.0"
    assert "restoreapp.venue" in finding.message


@pytest.mark.django_db
def test_a_reincluded_unmanaged_model_is_not_named(monkeypatch, settings):
    from dbs.registry import BackupRegistry

    monkeypatch.setattr("dbs.registry.backup_registry", BackupRegistry())
    settings.DBS_EXCLUDE_MODELS = ["-restoreapp.venue"]

    assert _finding("unmanaged models").message == "no unmanaged model is left out of backups"


@pytest.mark.django_db
def test_a_registry_keeps_unmanaged_models_in_the_developers_hands():
    finding = _finding("unmanaged models")

    assert finding.level == OK
    assert "restoreapp.venue" not in finding.message


@pytest.mark.django_db
def test_the_new_backup_defaults_are_explained():
    missing = _finding("missing source files")
    paths = _finding("backup paths")

    assert missing.level == OK and missing.since == "0.7.0"
    assert "--allow-missing-files" in missing.message
    assert paths.level == OK and paths.since == "0.7.0"
    assert "already exists" in paths.message


@pytest.mark.django_db
def test_no_path_map_needs_nothing():
    assert _finding("restore path map").level == OK


@pytest.mark.django_db
def test_a_malformed_path_map_is_reported(settings):
    settings.DBS_RESTORE_PATH_MAP = ["/srv/old", "/srv/new"]

    finding = _finding("restore path map")

    assert finding.level == WARN
    assert "DBS_RESTORE_PATH_MAP" in finding.remedy


@pytest.mark.django_db
def test_a_path_map_into_a_directory_no_root_allows_is_reported(settings, tmp_path):
    settings.DBS_RESTORE_ROOTS = [str(tmp_path / "allowed")]
    settings.DBS_RESTORE_PATH_MAP = {"/srv/old": str(tmp_path / "elsewhere")}

    finding = _finding("restore path map")

    assert finding.level == WARN
    assert str(tmp_path / "elsewhere") in finding.message

    settings.DBS_RESTORE_PATH_MAP = {"/srv/old": str(tmp_path / "allowed" / "media")}

    assert _finding("restore path map").level == OK
