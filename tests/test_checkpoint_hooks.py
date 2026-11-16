"""When migrate keeps a checkpoint, when it keeps none, and what a failure does."""

import sys
import types
from io import StringIO
from types import SimpleNamespace

import pytest
from django.apps import apps
from django.core.management import call_command, get_commands, load_command_class
from django.core.management.base import CommandError
from django.core.management.commands import makemigrations, migrate
from django.db.migrations import Migration
from django.db.models.signals import post_migrate, pre_migrate

from dbs import audit, checkpoints, jobs, leases
from dbs.management import underlying
from dbs.models import AuditEvent

PLAN = [(Migration("0002_currency", "shop"), False)]
BACKWARDS = [(Migration("0002_currency", "shop"), True)]
OWN = [(Migration("0007_next", "dbs"), False)]


@pytest.fixture
def real(monkeypatch, settings, tmp_path):
    settings.DBS_BACKUP_DIR = str(tmp_path / "backups")
    monkeypatch.setattr(checkpoints, "is_test_database", lambda connection: False)
    monkeypatch.setattr(checkpoints, "is_fresh", lambda connection: False)
    taken = []

    def take(role, *, using="default", plan=(), protect=()):
        made = checkpoints.Checkpoint(f"{role}.dbs", f"/backups/{role}.dbs", role, using, list(plan))
        taken.append(made)
        return made

    monkeypatch.setattr(checkpoints, "take", take)
    return taken


def before(plan=PLAN, **options):
    out = StringIO()
    checkpoints.before_migrate(None, using="default", plan=plan, stdout=out, **options)
    return out.getvalue()


def after(plan=PLAN, **options):
    out = StringIO()
    checkpoints.after_migrate(None, using="default", plan=plan, stdout=out, **options)
    return out.getvalue()


@pytest.mark.django_db
def test_a_migration_with_something_to_apply_is_kept_between_two_checkpoints(real):
    with checkpoints.session():
        said_before = before()
        said_after = after()

    assert [(made.role, made.plan) for made in real] == [
        ("before-migrate", ["shop.0002_currency"]),
        ("after-migrate", ["shop.0002_currency"]),
    ]
    assert "Checkpoint before this migration: /backups/before-migrate.dbs" in said_before
    assert "Checkpoint after this migration: /backups/after-migrate.dbs" in said_after


@pytest.mark.django_db
def test_a_backwards_step_is_named_with_a_minus(real):
    with checkpoints.session():
        before(BACKWARDS)

    assert real[0].plan == ["-shop.0002_currency"]


@pytest.mark.django_db
@pytest.mark.parametrize("plan", [None, [], OWN])
def test_nothing_to_apply_and_dbs_alone_keep_no_checkpoint(real, plan):
    with checkpoints.session():
        said = before(plan) + after(plan)

    assert real == [] and said == ""


@pytest.mark.django_db
def test_no_checkpoint_and_the_setting_keep_none_and_say_nothing(real, settings):
    with checkpoints.session(skip=True):
        said = before() + after()
    settings.DBS_MIGRATION_CHECKPOINTS = False
    with checkpoints.session():
        said += before() + after()

    assert real == [] and said == ""


@pytest.mark.django_db
def test_a_test_database_and_a_fresh_one_keep_none(real, monkeypatch):
    monkeypatch.setattr(checkpoints, "is_test_database", lambda connection: True)
    with checkpoints.session():
        said = before()
    monkeypatch.setattr(checkpoints, "is_test_database", lambda connection: False)
    monkeypatch.setattr(checkpoints, "is_fresh", lambda connection: True)
    with checkpoints.session():
        said += before()

    assert real == [] and said == ""


@pytest.mark.django_db
def test_a_project_without_a_backup_folder_is_told_once_and_only_when_asked_to_speak(
    real, settings
):
    settings.DBS_BACKUP_DIR = None

    with checkpoints.session():
        said = before()
        quiet = before(verbosity=0)

    assert "DBS keeps no checkpoint here: DBS_BACKUP_DIR is not set" in said
    assert quiet == "" and real == []


@pytest.mark.django_db
def test_a_checkpoint_before_that_fails_stops_the_migration(real, monkeypatch):
    def broken(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(checkpoints, "take", broken)

    with checkpoints.session(), pytest.raises(CommandError) as stopped:
        before()

    assert "the migration did not start" in str(stopped.value)
    assert "No space left on device" in str(stopped.value)
    assert "--no-checkpoint" in str(stopped.value)
    assert "DBS_MIGRATION_CHECKPOINTS = False" in str(stopped.value)


@pytest.mark.django_db
def test_a_checkpoint_after_that_fails_is_said_and_stops_nothing(real, monkeypatch, capsys):
    with checkpoints.session():
        before()

        def broken(*args, **kwargs):
            raise checkpoints.CheckpointError("the disk filled up")

        monkeypatch.setattr(checkpoints, "take", broken)
        said = after()

    assert said == ""
    assert "The migration is applied, but DBS could not keep a checkpoint" in capsys.readouterr().err


@pytest.mark.django_db
def test_no_checkpoint_after_when_there_was_none_before(real):
    with checkpoints.session():
        after()

    assert real == []


@pytest.mark.django_db
def test_a_migration_does_not_start_while_a_restore_runs(real):
    owner = leases.unique_owner()
    job = jobs.Job.begin(jobs.RESTORE, target="x.dbs", data={}, owner=owner)

    with checkpoints.session(), pytest.raises(CommandError) as stopped:
        before()
    job.close()
    audit.finish(job.event_id, data={})
    with checkpoints.session():
        before()

    assert "A restore is running" in str(stopped.value)
    assert [made.role for made in real] == ["before-migrate"]


@pytest.mark.django_db
def test_a_restore_job_whose_process_died_does_not_hold_migrations_back(real):
    AuditEvent.objects.create(action=jobs.RESTORE, status=audit.RUNNING, target_name="x.dbs")

    with checkpoints.session():
        before()

    assert [made.role for made in real] == ["before-migrate"]


@pytest.mark.django_db
def test_the_signals_of_migrate_reach_the_checkpoints(real):
    sender = apps.get_app_config("dbs")

    with checkpoints.session():
        pre_migrate.send(sender=sender, app_config=sender, using="default", plan=PLAN, verbosity=0)
        post_migrate.send(sender=sender, app_config=sender, using="default", plan=PLAN, verbosity=0)
        pre_migrate.send(
            sender=apps.get_app_config("auth"), using="default", plan=PLAN, verbosity=0
        )

    assert [made.role for made in real] == ["before-migrate", "after-migrate"]


def test_each_run_starts_with_no_checkpoint_of_the_one_before(real):
    with checkpoints.session() as first:
        first.before["default"] = "left over"
        with checkpoints.session() as second:
            assert second.before == {}
    with checkpoints.session() as third:
        assert third.before == {}


def test_the_hint_after_a_failed_migration_is_a_command_to_run():
    taken = checkpoints.Checkpoint("b.dbs", "/backups/b.dbs", "before-migrate", "default")
    elsewhere = checkpoints.Checkpoint("b.dbs", "/backups/b.dbs", "before-migrate", "ledger")

    assert 'python manage.py dbs restore "/backups/b.dbs" --flush' in checkpoints.restore_hint(taken)
    assert checkpoints.restore_hint(elsewhere).endswith("--flush --database ledger")


def test_migrate_and_makemigrations_are_the_commands_of_dbs_with_one_more_option():
    commands = get_commands()

    assert (commands["migrate"], commands["makemigrations"]) == ("dbs", "dbs")
    for name, base in (("migrate", migrate.Command), ("makemigrations", makemigrations.Command)):
        command = load_command_class("dbs", name)
        parser = command.create_parser("manage.py", name)
        assert isinstance(command, base)
        assert "--no-checkpoint" in parser.format_help()


def test_another_apps_migrate_is_built_on_not_replaced(monkeypatch, tmp_path):
    package = tmp_path / "tenants" / "management" / "commands"
    package.mkdir(parents=True)
    for folder in (tmp_path / "tenants", package.parent, package):
        (folder / "__init__.py").write_text("")
    (package / "migrate.py").write_text(
        "from django.core.management.commands.migrate import Command as Base\n\n\n"
        "class Command(Base):\n    tenants = True\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    configs = [
        apps.get_app_config("dbs"),
        SimpleNamespace(name="tenants", path=str(tmp_path / "tenants")),
        *apps.get_app_configs(),
    ]
    monkeypatch.setattr(underlying.apps, "get_app_configs", lambda: configs)

    found = underlying.underlying_command("migrate")

    assert found.tenants is True and issubclass(found, migrate.Command)
    assert underlying.underlying_command("makemigrations") is makemigrations.Command
    for name in [name for name in sys.modules if name.startswith("tenants")]:
        del sys.modules[name]
    assert isinstance(types.ModuleType("tenants"), types.ModuleType)


@pytest.mark.django_db
def test_migrate_with_nothing_to_apply_runs_as_before():
    out = StringIO()

    call_command("migrate", "--no-checkpoint", stdout=out, verbosity=1)
    call_command("migrate", stdout=out, verbosity=1)

    assert "No migrations to apply." in out.getvalue()
    assert "Checkpoint" not in out.getvalue()


@pytest.mark.django_db
def test_a_migration_that_fails_points_at_the_checkpoint_before_it(real, monkeypatch):
    def failing(self, *args, **options):
        checkpoints.before_migrate(None, using="default", plan=PLAN, stdout=self.stdout)
        raise RuntimeError("this migration is broken")

    monkeypatch.setattr(migrate.Command, "handle", failing)
    err = StringIO()

    with pytest.raises(RuntimeError):
        call_command("migrate", stdout=StringIO(), stderr=err)

    assert 'python manage.py dbs restore "/backups/before-migrate.dbs" --flush' in err.getvalue()


@pytest.mark.django_db
def test_makemigrations_checks_readiness_unless_it_only_checks(monkeypatch, settings, tmp_path):
    asked = []
    monkeypatch.setattr(checkpoints, "require_ready", lambda **options: asked.append(options))

    call_command("makemigrations", "dbs", "--check", stdout=StringIO())
    call_command("makemigrations", "dbs", "--dry-run", stdout=StringIO())
    call_command("makemigrations", "dbs", "--no-checkpoint", stdout=StringIO())
    assert asked == []

    call_command("makemigrations", "dbs", stdout=StringIO())
    assert len(asked) == 1


@pytest.mark.django_db
def test_readiness_is_not_asked_of_a_test_database_or_a_project_that_switched_it_off(
    settings, monkeypatch, tmp_path
):
    blocker = tmp_path / "a-file"
    blocker.write_text("x")
    settings.DBS_BACKUP_DIR = str(blocker / "backups")

    checkpoints.require_ready()

    monkeypatch.setattr(checkpoints, "is_test_database", lambda connection: False)
    with pytest.raises(CommandError) as refused:
        checkpoints.require_ready()
    settings.DBS_MIGRATION_CHECKPOINTS = False
    checkpoints.require_ready()

    assert "no migration was written" in str(refused.value)


def test_upgrade_says_whether_checkpoints_are_kept(settings, tmp_path):
    from dbs import upgrade
    from dbs.upgrade import OK, WARN

    settings.DBS_BACKUP_DIR = str(tmp_path)
    kept = upgrade.MigrationCheckpoints().check()
    settings.DBS_BACKUP_DIR = None
    nowhere = upgrade.MigrationCheckpoints().check()
    settings.DBS_MIGRATION_CHECKPOINTS = False
    off = upgrade.MigrationCheckpoints().check()

    assert kept.level == OK and "5 at most" in kept.message
    assert "migrate --no-checkpoint skips one" in kept.message
    assert nowhere.level == WARN and "DBS_BACKUP_DIR" in nowhere.remedy
    assert off.level == OK and "is off" in off.message
    assert upgrade.MigrationCheckpoints in upgrade.STEPS
