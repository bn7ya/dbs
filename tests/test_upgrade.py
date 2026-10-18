"""`manage.py dbs upgrade`: the checks, the fixes, and the refusal to lose backups."""

import stat
import sys
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from dbs import upgrade
from dbs.container import FORMAT_VERSION
from dbs.container.format import SEALED_PREFIX, container_version, seal_header
from dbs.container.stream import HEADER_SIZE, TRAILER_SIZE
from dbs.engine import create_backup, restore_backup, validate_backup
from dbs.keys import default_passphrase
from dbs.upgrade import ACTION, FIXED, OK, WARN, Converter
from tests.conftest import FAST_KDF
from tests.format1 import as_format1
from tests.testapp.models import Author

SHIPPED_CONVERTERS = dict(upgrade.CONVERTERS)

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


@pytest.fixture(autouse=True)
def own_folder(tmp_path_factory, monkeypatch):
    monkeypatch.chdir(tmp_path_factory.mktemp("project"))


@pytest.mark.django_db
def test_a_correctly_configured_project_is_up_to_date():
    report = upgrade.run_steps(apply_fixes=False)

    assert not report.blocked, [f for f in report.findings if f.level == "action"]
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


def test_a_dbs_client_config_left_behind_is_pointed_at_the_manager(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("DBS_CLIENT_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "dbs-client.toml").write_text("[servers.web]\nhost = 'h'\n")

    finding = upgrade.ClientRetired().check()

    assert finding.level == WARN
    assert "dbs-client.toml" in finding.message
    assert "django_dbs" in finding.remedy


def test_no_dbs_client_config_is_fine(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("DBS_CLIENT_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)

    assert upgrade.ClientRetired().check().level == OK


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


def test_the_install_command_pins_one_version():
    import sys

    command = upgrade.pinned_install_command("0.7.0")

    assert command == [sys.executable, "-m", "pip", "install", "django-dbs==0.7.0"]
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
    assert pip.calls[0][-1] == "django-dbs==9.9.9"
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
    future = stamp_version(backups / "current.dbs", backups / "future.dbs", 3)
    before = {path: path.read_bytes() for path in backups.iterdir()}

    with pytest.raises(CommandError, match="cannot be read"):
        run(backups=str(backups))

    assert {path: path.read_bytes() for path in backups.iterdir()} == before
    assert future.exists()


@pytest.mark.django_db
def test_an_unconvertible_backup_blocks_check_too(backups):
    stamp_version(backups / "current.dbs", backups / "future.dbs", 3)

    with pytest.raises(CommandError, match="not readable"):
        run(backups=str(backups), check=True)


@pytest.mark.django_db
def test_a_registered_converter_rewrites_and_keeps_the_original(backups, monkeypatch):
    source = stamp_version(backups / "current.dbs", backups / "old.dbs", 3)
    original = source.read_bytes()
    monkeypatch.setattr(upgrade, "CONVERTERS", {3: restamp(FORMAT_VERSION)})

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
    source = stamp_version(backups / "current.dbs", backups / "ancient.dbs", 4)
    monkeypatch.setattr(upgrade, "CONVERTERS", {4: restamp(3), 3: restamp(FORMAT_VERSION)})

    run(backups=str(backups))

    converted = backups / f"ancient.v{FORMAT_VERSION}.dbs"
    assert container_version(converted.read_bytes()) == FORMAT_VERSION
    assert container_version(source.read_bytes()) == 4


@pytest.mark.django_db
def test_a_converter_that_destroys_the_payload_beyond_repair_is_caught(backups, monkeypatch):
    stamp_version(backups / "current.dbs", backups / "old.dbs", 3)

    def wreck(data, passphrase):
        current = unwrap(data)
        patched = bytearray(current)
        copies_end = len(current) - HEADER_SIZE - 2 * TRAILER_SIZE
        patched[HEADER_SIZE:copies_end] = bytes(copies_end - HEADER_SIZE)
        return bytes(patched)

    monkeypatch.setattr(
        upgrade, "CONVERTERS", {3: Converter(produces=FORMAT_VERSION, convert=wreck)}
    )

    with pytest.raises(CommandError, match="cannot be read"):
        run(backups=str(backups))

    assert sorted(path.name for path in backups.iterdir()) == ["current.dbs", "old.dbs"]


@pytest.mark.django_db
def test_a_conversion_never_takes_a_name_that_is_in_use(backups, monkeypatch):
    stamp_version(backups / "current.dbs", backups / "old.dbs", 3)
    squatter = backups / f"old.v{FORMAT_VERSION}.dbs"
    squatter.write_bytes(b"someone else's file")
    monkeypatch.setattr(upgrade, "CONVERTERS", {3: restamp(FORMAT_VERSION)})

    with pytest.raises(CommandError, match="cannot be read"):
        run(backups=str(backups))

    assert squatter.read_bytes() == b"someone else's file"
    converted = backups / f"old.v{FORMAT_VERSION}-2.dbs"
    assert container_version(converted.read_bytes()) == FORMAT_VERSION


@pytest.mark.django_db
def test_a_converted_backup_is_converted_once(backups, monkeypatch):
    stamp_version(backups / "current.dbs", backups / "old.dbs", 3)
    monkeypatch.setattr(upgrade, "CONVERTERS", {3: restamp(FORMAT_VERSION)})

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
    stamp_version(backups / "current.dbs", backups / name, 3)
    monkeypatch.setattr(upgrade, "CONVERTERS", {3: restamp(FORMAT_VERSION)})

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
    stamp_version(backups / "current.dbs", backups / "old.dbs", 3)

    def explode(data, passphrase):
        raise ValueError("no")

    monkeypatch.setattr(
        upgrade, "CONVERTERS", {3: Converter(produces=FORMAT_VERSION, convert=explode)}
    )

    with pytest.raises(CommandError, match="cannot be read"):
        run(backups=str(backups))


def test_the_backup_format_step_explains_format_2():
    finding = upgrade.BackupFormat().check()

    assert finding.level == OK
    assert f"format {FORMAT_VERSION}" in finding.message
    assert "format 1 backups still restore" in finding.message
    assert "dbs upgrade --backups DIR" in finding.message


@pytest.mark.parametrize(
    "name, value",
    [("DBS_KDF_TIME_COST", 11), ("DBS_KDF_MEMORY_COST", 256 * 1024 + 1), ("DBS_KDF_TIME_COST", "x")],
)
def test_the_backup_format_step_reports_kdf_settings_format_2_refuses(settings, name, value):
    setattr(settings, name, value)

    finding = upgrade.BackupFormat().check()

    assert finding.level == ACTION
    assert name in finding.message
    assert "DBS_KDF_TIME_COST = 10" in finding.remedy


def test_kdf_settings_at_the_format_2_ceiling_are_fine(settings):
    settings.DBS_KDF_TIME_COST = 10
    settings.DBS_KDF_MEMORY_COST = 256 * 1024

    assert upgrade.BackupFormat().check().level == OK


@pytest.mark.django_db
def test_a_format_1_backup_is_converted_beside_the_original(backups, monkeypatch, settings):
    monkeypatch.setattr(upgrade, "CONVERTERS", SHIPPED_CONVERTERS)
    passphrase = default_passphrase()
    format1 = as_format1(create_backup(passphrase, kdf_params=FAST_KDF), passphrase)
    source = backups / "old.dbs"
    source.write_bytes(format1)

    printed = run(backups=str(backups))

    assert "original is untouched" in printed
    assert source.read_bytes() == format1
    converted = backups / f"old.v{FORMAT_VERSION}.dbs"
    assert container_version(converted.read_bytes()) == FORMAT_VERSION
    assert stat.S_IMODE(converted.stat().st_mode) == 0o600
    assert sorted(path.name for path in backups.iterdir()) == [
        "current.dbs",
        "old.dbs",
        converted.name,
    ]
    checked = validate_backup(converted, passphrase)
    assert checked.ok and checked.decrypted_ok
    assert checked.stats["records"] == validate_backup(format1, passphrase).stats["records"]
    Author.objects.all().delete()
    restore_backup(converted, passphrase)
    assert Author.objects.filter(name="Ada").exists()


def test_the_shipped_converter_turns_format_1_into_the_current_format():
    assert SHIPPED_CONVERTERS[1].produces == FORMAT_VERSION == 2
    assert SHIPPED_CONVERTERS[1].needs_passphrase


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
    assert commands["dbs_upgrade"] == "dbs"
    assert "dbs-upgrade" not in commands
    assert load_command_class("dbs", "dbs_upgrade").__module__.endswith("dbs_upgrade")


def test_the_umbrella_lists_upgrade():
    from dbs.management.commands.dbs import SUBCOMMANDS

    assert SUBCOMMANDS["upgrade"][0] == "dbs_upgrade"
    out = StringIO()
    call_command("dbs", stdout=out)
    assert "manage.py dbs upgrade" in out.getvalue()


def without(monkeypatch, *modules):
    for module in modules:
        monkeypatch.setitem(sys.modules, module, None)


def test_missing_numpy_is_reported(monkeypatch):
    import importlib

    real_import = importlib.import_module

    def without_numpy(name, *args, **kwargs):
        if name == "numpy":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", without_numpy)

    finding = upgrade.Dependencies().check()

    assert finding.level == ACTION
    assert "numpy" in finding.message
    assert finding.remedy == 'pip install --force-reinstall "django-dbs"'


def test_everything_dbs_uses_is_installed():
    finding = upgrade.Dependencies().check()

    assert finding.level == OK
    assert "manager" in finding.message


def test_a_scikit_learn_that_fails_to_import_is_reported(monkeypatch):
    import importlib

    real = importlib.import_module

    def broken(name, *args, **kwargs):
        if name == "sklearn":
            raise ValueError("numpy.dtype size changed, may indicate binary incompatibility")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", broken)

    finding = upgrade.Dependencies().check()

    assert finding.level == ACTION
    assert "binary incompatibility" in finding.message


def test_a_requirement_naming_an_old_extra_is_warned(tmp_path, settings):
    settings.BASE_DIR = tmp_path
    (tmp_path / "requirements.txt").write_text("django-dbs[guard,manager]==0.7.0\n")

    finding = upgrade.RetiredExtras().check()

    assert finding.level == WARN
    assert "requirements.txt" in finding.message
    assert "without the brackets" in finding.remedy


def test_plain_django_dbs_requirements_are_ok(tmp_path, settings):
    settings.BASE_DIR = tmp_path
    (tmp_path / "requirements.txt").write_text("django-dbs==0.8.0\n")

    assert upgrade.RetiredExtras().check().level == OK


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


REMOVED_PUSH_SETTINGS = (
    "DBS_SSH_TARGETS",
    "DBS_SCHEDULE_PUSH_TARGET",
    "DBS_SCHEDULE_KEEP_REMOTE",
    "DBS_ADMIN_CONSOLE_SHELL",
)


@pytest.mark.django_db
def test_a_project_that_pushes_nowhere_needs_nothing():
    assert upgrade.PulledBackups().check().level == OK


@pytest.mark.django_db
@pytest.mark.parametrize("name", REMOVED_PUSH_SETTINGS)
def test_a_removed_push_setting_points_at_the_manager(settings, name):
    setattr(settings, name, {"offsite": {"host": "h"}})

    finding = upgrade.PulledBackups().check()

    assert finding.level == WARN
    assert name in finding.message
    assert "django_dbs server add" in finding.remedy
    assert ("SSHTarget.from_settings" in finding.remedy) == (name == "DBS_SSH_TARGETS")


def historical(model, migration="0004_schedule_lease"):
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    state = MigrationExecutor(connection).loader.project_state(("dbs", migration))
    return state.apps.get_model("dbs", model)


@pytest.mark.django_db(transaction=True)
def test_sftp_targets_are_reported_before_and_after_the_migration_drops_them():
    call_command("migrate", "dbs", "0004", verbosity=0)
    try:
        historical("BackupTarget").objects.create(
            name="offsite",
            host="backups.example.com",
            username="deploy",
            remote_dir="/var/backups",
            secret_password="hunter2",
        )

        before = upgrade.PulledBackups().check()
        call_command("migrate", "dbs", verbosity=0)
        after = upgrade.PulledBackups().check()
    finally:
        call_command("migrate", "dbs", verbosity=0)

    assert before.level == WARN
    assert "offsite (deploy@backups.example.com:22)" in before.message
    assert after.level == OK
    assert "offsite (deploy@backups.example.com:22)" in after.message
    from dbs.models import AuditEvent

    removed = AuditEvent.objects.get(action="target.remove")
    assert removed.target_name == "offsite"
    assert removed.data["host"] == "backups.example.com"
    assert "django_dbs server add" in removed.detail
    assert "hunter2" not in f"{removed.data}{removed.detail}"
    assert set(removed.data) == {"host", "port", "username", "remote_dir"}


@pytest.mark.django_db
def test_keeping_five_or_fewer_needs_nothing(settings):
    settings.DBS_SCHEDULE_KEEP = 5

    assert upgrade.KeepAtMostFive().check().level == OK


@pytest.mark.django_db
@pytest.mark.parametrize("keep", [6, 14, 0, "lots"])
def test_a_keep_setting_outside_one_to_five_is_reported(settings, keep):
    settings.DBS_SCHEDULE_KEEP = keep

    finding = upgrade.KeepAtMostFive().check()

    assert finding.level == WARN
    assert f"DBS_SCHEDULE_KEEP is {keep}" in finding.message
    assert finding.remedy.startswith("DBS_SCHEDULE_KEEP = 5")


@pytest.mark.django_db(transaction=True)
def test_the_migration_lowers_a_schedule_keeping_more_than_five():
    call_command("migrate", "dbs", "0004", verbosity=0)
    try:
        historical("BackupSchedule").objects.create(interval="6h", keep=9)

        before = upgrade.KeepAtMostFive().check()
        call_command("migrate", "dbs", verbosity=0)
        after = upgrade.KeepAtMostFive().check()
    finally:
        call_command("migrate", "dbs", verbosity=0)

    from dbs.models import BackupSchedule

    assert before.level == WARN and "keeps 9" in before.message
    assert after.level == OK
    assert BackupSchedule.objects.get().keep == 5


@pytest.mark.django_db(transaction=True)
def test_the_audit_chain_step_applies_its_migration():
    call_command("migrate", "dbs", "0004", verbosity=0)
    try:
        step = upgrade.AuditChain()

        reported = step.check()
        applied = step.fix()

        assert reported.level == ACTION
        assert reported.remedy == "python manage.py migrate dbs"
        assert applied.level == FIXED
        assert step.check().level == OK
        assert "dbs audit verify" in step.check().message
    finally:
        call_command("migrate", "dbs", verbosity=0)


@pytest.mark.django_db
def test_nothing_naming_the_contrib_views_is_ok():
    finding = upgrade.ContribViewsRemoved().check()

    assert finding.level == OK


@pytest.mark.django_db
def test_an_urlconf_that_still_includes_the_contrib_views_needs_action(
    tmp_path, settings, monkeypatch
):
    package = tmp_path / "oldsite"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "urls.py").write_text(
        'from django.urls import include, path\n'
        'urlpatterns = [path("dbs/", include("dbs.contrib.urls"))]\n'
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    settings.ROOT_URLCONF = "oldsite.urls"

    finding = upgrade.ContribViewsRemoved().check()

    assert finding.level == ACTION
    assert "oldsite.urls" in finding.message
    assert 'include("dbs.contrib.urls")' in finding.remedy
    assert "oldsite.urls" not in sys.modules


@pytest.mark.django_db
def test_upgrade_reports_a_broken_urlconf_instead_of_crashing(tmp_path, settings, monkeypatch):
    package = tmp_path / "brokensite"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "urls.py").write_text(
        'from django.urls import include, path\n'
        'urlpatterns = [path("dbs/", include("dbs.contrib.urls"))]\n'
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    settings.ROOT_URLCONF = "brokensite.urls"
    out = StringIO()

    with pytest.raises(CommandError):
        call_command("dbs", "upgrade", "--check", offline=True, stdout=out, skip_checks=False)

    assert "contrib views" in out.getvalue()


def test_a_script_still_running_the_old_upgrade_name_is_named(tmp_path, settings):
    settings.BASE_DIR = tmp_path
    (tmp_path / "deploy.sh").write_text("python manage.py dbs-upgrade --check\n")
    (tmp_path / "Makefile").write_text("upgrade:\n\tpython manage.py dbs upgrade\n")

    finding = upgrade.CommandNames().check()

    assert finding.level == WARN
    assert "deploy.sh" in finding.message
    assert "Makefile" not in finding.message


def test_no_old_command_name_is_ok(tmp_path, settings):
    settings.BASE_DIR = tmp_path

    assert upgrade.CommandNames().check().level == OK


def test_old_partial_files_are_named_and_left_alone(tmp_path, settings):
    from dbs.naming import backup_filename

    settings.DBS_BACKUP_DIR = str(tmp_path)
    old = tmp_path / (backup_filename("web") + ".part")
    old.write_bytes(b"x")
    (tmp_path / "notes.part").write_bytes(b"x")

    finding = upgrade.LegacyPartials().check()

    assert finding.level == WARN
    assert finding.remedy.startswith("rm ")
    assert old.name in finding.remedy
    assert "notes.part" not in finding.remedy
    assert old.exists()


def test_no_old_partial_files_is_ok(tmp_path, settings):
    settings.DBS_BACKUP_DIR = str(tmp_path)

    assert upgrade.LegacyPartials().check().level == OK


def test_the_ssh_target_keys_step_names_the_current_keys():
    finding = upgrade.SSHTargetKeys().check()

    assert finding.level == OK
    assert "key_filename" in finding.message


@pytest.mark.django_db
def test_mysql_reads_say_nothing_changes_on_another_database():
    from django.db import connection

    finding = upgrade.MySQLReads().check()

    if connection.vendor == "mysql":
        assert finding.level in (OK, WARN)
        assert "consistent snapshot" in finding.message
    else:
        assert finding.level == OK
        assert "not MySQL" in finding.message


@pytest.mark.django_db
def test_a_small_mysql_packet_is_warned(monkeypatch):
    from django.db import connection

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql):
            assert "max_allowed_packet" in sql

        def fetchone(self):
            return (16 * 1024 * 1024,)

    monkeypatch.setattr(connection, "vendor", "mysql")
    monkeypatch.setattr(connection, "cursor", lambda: Cursor())

    finding = upgrade.MySQLReads().check()

    assert finding.level == WARN
    assert "16 MiB" in finding.message
    assert "max_allowed_packet = 256M" in finding.remedy


@pytest.mark.django_db
def test_sqlite_writes_say_nothing_changes_on_another_database_or_in_memory():
    from django.db import connection

    finding = upgrade.SQLiteWrites().check()

    assert finding.level == OK
    if connection.vendor == "sqlite":
        assert "in memory" in finding.message
    else:
        assert "not SQLite" in finding.message


class Journal:
    def __init__(self, mode):
        self.mode = mode

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql):
        assert sql == "PRAGMA journal_mode"

    def fetchone(self):
        return (self.mode,)


@pytest.mark.django_db
def test_sqlite_in_rollback_journal_mode_is_warned(monkeypatch):
    import django
    from django.db import connection

    monkeypatch.setattr(connection, "vendor", "sqlite")
    monkeypatch.setattr(connection, "cursor", lambda: Journal("delete"))
    monkeypatch.setitem(connection.settings_dict, "OPTIONS", {})

    finding = upgrade.SQLiteWrites().check()

    assert finding.level == WARN
    assert "the journal mode is delete" in finding.message
    assert "database is locked" in finding.message
    assert "journal_mode=WAL" in finding.remedy
    if django.VERSION >= (5, 1):
        assert "transactions start deferred" in finding.message
        assert '"transaction_mode": "IMMEDIATE"' in finding.remedy


@pytest.mark.django_db
def test_sqlite_in_wal_mode_with_immediate_transactions_is_fine(monkeypatch):
    from django.db import connection

    monkeypatch.setattr(connection, "vendor", "sqlite")
    monkeypatch.setattr(connection, "cursor", lambda: Journal("wal"))
    monkeypatch.setitem(
        connection.settings_dict, "OPTIONS", {"transaction_mode": "IMMEDIATE"}
    )

    finding = upgrade.SQLiteWrites().check()

    assert finding.level == OK
    assert "WAL mode" in finding.message


def test_panel_jobs_in_the_web_process_are_named(settings):
    settings.DBS_JOB_PROCESS = False

    finding = upgrade.PanelJobProcess().check()

    assert finding.level == OK
    assert "inside the web process" in finding.message


def test_panel_jobs_whose_interpreter_cannot_load_the_project_warn(settings, monkeypatch):
    from dbs import job_process

    settings.DBS_JOB_PROCESS = True
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "tests.settings")
    monkeypatch.setattr(job_process, "probe", lambda: "ModuleNotFoundError: No module named 'site'")

    finding = upgrade.PanelJobProcess().check()

    assert finding.level == WARN
    assert "ModuleNotFoundError" in finding.message
    assert "DBS_JOB_PYTHON" in finding.remedy


def test_panel_jobs_that_can_start_report_their_limits(settings, monkeypatch):
    from dbs import job_process

    settings.DBS_JOB_PROCESS = True
    settings.DBS_JOB_TIME_LIMIT = "2h"
    settings.DBS_JOB_MEMORY_LIMIT = "1G"
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "tests.settings")
    monkeypatch.setattr(job_process, "probe", lambda: "")

    finding = upgrade.PanelJobProcess().check()

    assert finding.level == OK
    assert "2 h" in finding.message and "1024 MiB" in finding.message


def test_an_unreadable_job_limit_needs_action(settings):
    settings.DBS_JOB_PROCESS = True
    settings.DBS_JOB_MEMORY_LIMIT = "lots"

    finding = upgrade.PanelJobProcess().check()

    assert finding.level == ACTION
    assert "512M" in finding.message


def test_the_probe_starts_the_project_in_a_fresh_interpreter(monkeypatch):
    from dbs import job_process

    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "tests.settings")

    assert job_process.probe() == ""
