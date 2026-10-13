"""`manage.py dbs upgrade`: the checks, the fixes, and the refusal to lose backups."""

import stat
import struct
import sys
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from dbs import upgrade
from dbs.container.format import FORMAT_VERSION, container_version
from dbs.engine import create_backup
from dbs.keys import default_passphrase
from dbs.upgrade import ACTION, FIXED, OK, WARN, Converter
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


class Distribution:
    def __init__(self, site, direct_url=None):
        self.site = site
        self.direct_url = direct_url

    def read_text(self, name):
        return self.direct_url if name == "direct_url.json" else None

    def locate_file(self, path):
        return self.site / path


def installed_package(root):
    package = root / "dbs"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    return package


def test_a_debian_dist_packages_install_is_an_installed_package(tmp_path):
    site = tmp_path / "usr" / "lib" / "python3" / "dist-packages"
    package = installed_package(site)

    assert upgrade.is_source_checkout(package, Distribution(site)) is False


def test_a_site_packages_install_is_an_installed_package(tmp_path):
    site = tmp_path / "venv" / "lib" / "python3.12" / "site-packages"
    package = installed_package(site)
    pinned = '{"url": "https://files.pythonhosted.org/django_dbs.whl", "archive_info": {}}'

    assert upgrade.is_source_checkout(package, Distribution(site, pinned)) is False


def test_an_editable_install_is_a_source_checkout(tmp_path):
    site = tmp_path / "site-packages"
    package = installed_package(site)
    editable = '{"url": "file:///src/dbs", "dir_info": {"editable": true}}'

    assert upgrade.is_source_checkout(package, Distribution(site, editable)) is True


def test_a_package_beside_a_project_file_is_a_source_checkout(tmp_path):
    package = installed_package(tmp_path / "dbs-checkout")
    (tmp_path / "dbs-checkout" / "pyproject.toml").write_text("[project]\n")

    assert upgrade.is_source_checkout(package, Distribution(tmp_path / "dbs-checkout")) is True


def test_a_copy_that_shadows_the_installed_one_is_a_source_checkout(tmp_path):
    package = installed_package(tmp_path / "elsewhere")
    site = tmp_path / "site-packages"
    installed_package(site)

    assert upgrade.is_source_checkout(package, Distribution(site)) is True


def test_no_installed_distribution_is_a_source_checkout(tmp_path):
    assert upgrade.is_source_checkout(installed_package(tmp_path), None) is True


def test_an_interpreter_outside_a_virtual_environment_is_the_system_one(tmp_path):
    base = tmp_path / "usr"
    venv = tmp_path / "venv"
    conda = tmp_path / "conda"
    for directory in (base, venv, conda / "conda-meta"):
        directory.mkdir(parents=True)

    assert upgrade.is_system_interpreter(str(base), str(base)) is True
    assert upgrade.is_system_interpreter(str(venv), str(base)) is False
    assert upgrade.is_system_interpreter(str(conda), str(conda)) is False


def test_the_install_command_pins_one_version_with_the_installed_extras():
    import sys

    command = upgrade.pinned_install_command("0.7.0", ["manager", "guard"])

    assert command == [
        sys.executable, "-m", "pip", "install", "django-dbs[guard,manager]==0.7.0"
    ]
    assert upgrade.pinned_install_command("0.7.0")[-1] == "django-dbs==0.7.0"
    assert "--upgrade" not in command and "-U" not in command


@pytest.mark.parametrize("text", ["0.7.0", "1.0", "1.2.3rc1", "0.7.0.post1", "2.0.0.dev3"])
def test_version_numbers_are_accepted(text):
    assert upgrade.is_version(text)


@pytest.mark.parametrize(
    "text", ["", "latest", "0.7.0; rm -rf /", ">=0.7", "0.7.0 --pre", "0.7.0\n"]
)
def test_anything_else_is_not_a_version(text):
    assert not upgrade.is_version(text)


def test_requirement_files_that_name_django_dbs_are_found(tmp_path):
    (tmp_path / "requirements.txt").write_text("Django>=5.2\ndjango-dbs==0.6.0\n")
    (tmp_path / "requirements-dev.txt").write_text("pytest\n")
    (tmp_path / "uv.lock").write_text('name = "django-dbs"\n')

    found = [path.name for path in upgrade.requirement_files(tmp_path)]

    assert found == ["requirements.txt", "uv.lock"]


class Pip:
    def __init__(self, returncode=0):
        self.calls = []
        self.returncode = returncode

    def __call__(self, command, **kwargs):
        import subprocess

        self.calls.append(command)
        return subprocess.CompletedProcess(command, self.returncode, "", "pip said no")


@pytest.fixture
def pip(monkeypatch):
    from dbs.management.commands import dbs_upgrade

    recorder = Pip()
    monkeypatch.setattr(dbs_upgrade.subprocess, "run", recorder)
    monkeypatch.setattr(dbs_upgrade, "is_editable_install", lambda: False)
    monkeypatch.setattr(dbs_upgrade, "is_system_interpreter", lambda: False)
    return recorder


@pytest.mark.django_db
def test_self_installs_the_exact_version_it_shows(pip, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "requirements.txt").write_text("django-dbs==0.6.0\n")

    printed = run(self_update=True, target_version="9.9.9", yes=True)

    assert len(pip.calls) == 1
    assert pip.calls[0][1:4] == ["-m", "pip", "install"]
    assert pip.calls[0][-1].startswith("django-dbs[") and pip.calls[0][-1].endswith("]==9.9.9")
    assert "--upgrade" not in pip.calls[0]
    assert pip.calls[0][-1] in printed
    assert "Pin django-dbs==9.9.9 in requirements.txt" in printed


@pytest.mark.django_db
def test_self_resolves_the_newest_release_before_installing(pip, monkeypatch):
    from dbs.management.commands import dbs_upgrade

    monkeypatch.setattr(dbs_upgrade, "latest_release", lambda: "9.9.9")

    run(self_update=True, yes=True, offline=False)

    assert pip.calls[0][-1].endswith("==9.9.9")


@pytest.mark.django_db
def test_self_asks_before_installing(pip):
    with pytest.raises(CommandError, match="Nothing was installed"):
        run(self_update=True, target_version="9.9.9")

    assert pip.calls == []


@pytest.mark.django_db
def test_self_leaves_a_system_interpreter_alone(pip, monkeypatch):
    from dbs.management.commands import dbs_upgrade

    monkeypatch.setattr(dbs_upgrade, "is_system_interpreter", lambda: True)

    with pytest.raises(CommandError, match="--system-python"):
        run(self_update=True, target_version="9.9.9", yes=True)
    assert pip.calls == []

    run(self_update=True, target_version="9.9.9", yes=True, system_python=True)
    assert len(pip.calls) == 1


@pytest.mark.django_db
def test_self_refuses_on_a_source_checkout(pip, monkeypatch):
    from dbs.management.commands import dbs_upgrade

    monkeypatch.setattr(dbs_upgrade, "is_editable_install", lambda: True)

    printed = run(self_update=True, target_version="9.9.9", yes=True)

    assert "refusing --self on a source checkout" in printed
    assert pip.calls == []


@pytest.mark.django_db
def test_self_does_nothing_when_the_version_is_installed(pip):
    printed = run(self_update=True, target_version=upgrade.installed_version(), yes=True)

    assert "already installed" in printed
    assert pip.calls == []


@pytest.mark.django_db
def test_self_offline_needs_a_version(pip):
    with pytest.raises(CommandError, match="--to VERSION"):
        run(self_update=True, yes=True)

    assert pip.calls == []


@pytest.mark.django_db
def test_self_rejects_what_is_not_a_version(pip):
    with pytest.raises(CommandError, match="not a django-dbs version"):
        run(self_update=True, target_version="0.7; echo", yes=True)

    assert pip.calls == []


@pytest.mark.django_db
def test_self_rejects_a_version_pypi_does_not_have(pip, monkeypatch):
    from dbs.management.commands import dbs_upgrade

    monkeypatch.setattr(dbs_upgrade, "release_exists", lambda version: False)

    with pytest.raises(CommandError, match="not on PyPI"):
        run(self_update=True, target_version="9.9.9", yes=True, offline=False)

    assert pip.calls == []


@pytest.mark.django_db
def test_to_without_self_is_refused(pip):
    with pytest.raises(CommandError, match="add --self"):
        run(target_version="9.9.9")


@pytest.mark.django_db
def test_a_failing_pip_is_reported(pip):
    pip.returncode = 1

    with pytest.raises(CommandError, match="pip failed"):
        run(self_update=True, target_version="9.9.9", yes=True)


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
    converted = backups / f"old.v{FORMAT_VERSION}.dbs"
    assert converted.is_file()
    assert container_version(converted.read_bytes()) == FORMAT_VERSION
    assert stat.S_IMODE(converted.stat().st_mode) == 0o600
    assert sorted(path.name for path in backups.iterdir()) == [
        "current.dbs",
        "old.dbs",
        converted.name,
    ]


@pytest.mark.django_db
def test_conversion_chains_across_several_versions(backups, monkeypatch):
    source = stamp_version(backups / "current.dbs", backups / "ancient.dbs", 3)
    monkeypatch.setattr(upgrade, "CONVERTERS", {3: restamp(2), 2: restamp(FORMAT_VERSION)})

    run(backups=str(backups))

    converted = backups / f"ancient.v{FORMAT_VERSION}.dbs"
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

    assert sorted(path.name for path in backups.iterdir()) == ["current.dbs", "old.dbs"]


@pytest.mark.django_db
def test_a_conversion_never_takes_a_name_that_is_in_use(backups, monkeypatch):
    stamp_version(backups / "current.dbs", backups / "old.dbs", 2)
    squatter = backups / f"old.v{FORMAT_VERSION}.dbs"
    squatter.write_bytes(b"someone else's file")
    monkeypatch.setattr(upgrade, "CONVERTERS", {2: restamp(FORMAT_VERSION)})

    with pytest.raises(CommandError, match="cannot be read"):
        run(backups=str(backups))

    assert squatter.read_bytes() == b"someone else's file"
    converted = backups / f"old.v{FORMAT_VERSION}-2.dbs"
    assert container_version(converted.read_bytes()) == FORMAT_VERSION


@pytest.mark.django_db
def test_a_converted_backup_is_converted_once(backups, monkeypatch):
    stamp_version(backups / "current.dbs", backups / "old.dbs", 2)
    monkeypatch.setattr(upgrade, "CONVERTERS", {2: restamp(FORMAT_VERSION)})

    run(backups=str(backups))
    printed = run(backups=str(backups), check=True)

    assert f"old.dbs was converted earlier to old.v{FORMAT_VERSION}.dbs" in printed
    assert sorted(path.name for path in backups.iterdir()) == [
        "current.dbs",
        "old.dbs",
        f"old.v{FORMAT_VERSION}.dbs",
    ]


@pytest.mark.django_db
def test_a_converted_backup_keeps_a_backup_name(backups, monkeypatch):
    from dbs.naming import backup_prefix, is_backup_name, parse_backup_moment

    name = "nightly-20260101-020000Z.dbs"
    stamp_version(backups / "current.dbs", backups / name, 2)
    monkeypatch.setattr(upgrade, "CONVERTERS", {2: restamp(FORMAT_VERSION)})

    run(backups=str(backups))

    converted = f"nightly-20260101-020000Z.v{FORMAT_VERSION}.dbs"
    assert (backups / converted).is_file()
    assert is_backup_name(converted, "nightly")
    assert backup_prefix(converted) == "nightly"
    assert parse_backup_moment(converted) == parse_backup_moment(name)


def test_conversion_names():
    source = Path("/backups/site-20260101-020000Z.dbs")

    assert upgrade.conversion_name(source, 2).name == "site-20260101-020000Z.v2.dbs"
    assert upgrade.conversion_name(source, 2, 3).name == "site-20260101-020000Z.v2-3.dbs"
    assert upgrade.conversion_name(Path("plain"), 2).name == "plain.v2.dbs"


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


def without(monkeypatch, *modules):
    for module in modules:
        monkeypatch.setitem(sys.modules, module, None)


def test_the_guard_extra_is_fine_when_scikit_learn_is_installed():
    assert upgrade.GuardExtra().check().level == OK


def test_the_guard_middleware_without_scikit_learn_asks_for_the_guard_extra(monkeypatch):
    without(monkeypatch, "sklearn")

    finding = upgrade.GuardExtra().check()

    assert finding.level == ACTION
    assert "DBSSecurityMiddleware" in finding.message
    assert "ModuleNotFoundError" in finding.message
    assert finding.remedy == 'pip install "django-dbs[guard]"'


def test_a_scikit_learn_that_fails_to_import_counts_as_missing(monkeypatch):
    import importlib

    real = importlib.import_module

    def broken(name, *args, **kwargs):
        if name == "sklearn":
            raise ValueError("numpy.dtype size changed, may indicate binary incompatibility")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", broken)

    finding = upgrade.GuardExtra().check()

    assert finding.level == ACTION
    assert "binary incompatibility" in finding.message


@pytest.mark.django_db
def test_without_the_guard_middleware_scikit_learn_is_not_needed(settings, monkeypatch):
    without(monkeypatch, "sklearn")
    settings.MIDDLEWARE = [m for m in settings.MIDDLEWARE if "DBSSecurityMiddleware" not in m]

    assert upgrade.GuardExtra().check().level == OK
    assert levels(upgrade.run_steps(apply_fixes=False))["guard extra"] == OK


def test_the_manager_extra_is_reported_when_installed():
    finding = upgrade.ManagerExtra().check()

    assert finding.level == OK
    assert "django_dbs run" in finding.message


@pytest.mark.django_db
def test_a_missing_manager_extra_is_named_but_never_demanded(monkeypatch):
    without(monkeypatch, "waitress")

    finding = upgrade.ManagerExtra().check()

    assert finding.level == OK
    assert "waitress" in finding.message and "paramiko" not in finding.message
    assert 'pip install "django-dbs[manager]"' in finding.remedy
    assert not upgrade.run_steps(apply_fixes=False).blocked
