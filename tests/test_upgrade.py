"""`manage.py dbs upgrade`: the checks, the fixes, and the refusal to lose backups."""

import struct
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from dbs import upgrade
from dbs.container.format import FORMAT_VERSION, container_version
from dbs.engine import create_backup
from dbs.keys import default_passphrase
from dbs.upgrade import ACTION, OK, WARN, Converter
from tests.testapp.models import Author

OFFLINE = {"offline": True}

VERSION_OFFSET = 8


def run(**options):
    out = StringIO()
    call_command("dbs", "upgrade", stdout=out, stderr=StringIO(), **dict(OFFLINE, **options))
    return out.getvalue()


def levels(report):
    return {finding.step: finding.level for finding in report.findings}


def stamp_version(source: Path, destination: Path, version: int):
    data = bytearray(source.read_bytes())
    struct.pack_into(">H", data, VERSION_OFFSET, version)
    destination.write_bytes(bytes(data))
    return destination


def restamp(version):
    def convert(data, passphrase):
        patched = bytearray(data)
        struct.pack_into(">H", patched, VERSION_OFFSET, version)
        return bytes(patched)

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
        from dbs.container.format import HEADER_SIZE

        patched = bytearray(data)
        struct.pack_into(">H", patched, VERSION_OFFSET, FORMAT_VERSION)
        patched[HEADER_SIZE:] = b"\x00" * (len(patched) - HEADER_SIZE)
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
