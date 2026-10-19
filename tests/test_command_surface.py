"""The manage.py dbs umbrella, its equal names django_dbs and django-dbs, and the original command names."""

from io import StringIO

import pytest
from django.core.management import call_command, get_commands, load_command_class

from dbs.management.commands.dbs import SUBCOMMANDS
from tests.testapp.models import Author

FAST = {"kdf_time": 1, "kdf_memory": 8192}


def test_the_registry_carries_every_name():
    commands = get_commands()

    for name in ("dbs", "django_dbs", "django-dbs"):
        assert commands[name] == "dbs", name
    for name in ("dbs_backup", "dbs_restore", "dbs_validate", "dbs_schedule"):
        assert commands[name] == "dbs", name


def test_the_hyphenated_name_is_a_real_command_module():
    assert load_command_class("dbs", "django-dbs").__module__.endswith("django-dbs")


def test_the_old_alias_for_upgrade_is_gone():
    assert "dbs-upgrade" not in get_commands()


def test_bare_dbs_prints_an_overview():
    out = StringIO()

    call_command("dbs", stdout=out)

    printed = out.getvalue()
    assert "/admin/dbs/" in printed
    assert "dbs ai" in printed
    for name in SUBCOMMANDS:
        assert f"manage.py dbs {name}" in printed


@pytest.mark.parametrize("name", ["django_dbs", "django-dbs"])
def test_every_name_prints_the_same_overview_without_a_tip(name):
    out = StringIO()

    call_command(name, stdout=out)

    assert "manage.py dbs backup" in out.getvalue()
    assert "Tip" not in out.getvalue()
    assert "old name" not in out.getvalue()


def test_every_subcommand_is_a_real_command():
    for name, (module, _) in SUBCOMMANDS.items():
        assert load_command_class("dbs", module) is not None, name


@pytest.mark.django_db
def test_the_umbrella_takes_and_restores_a_backup(tmp_path):
    Author.objects.create(name="Ada")
    output = tmp_path / "via-umbrella.dbs"

    call_command("dbs", "backup", str(output), stdout=StringIO(), **FAST)
    assert output.exists()

    call_command("dbs", "validate", str(output), stdout=StringIO())

    Author.objects.all().delete()
    call_command("dbs", "restore", str(output), stdout=StringIO())
    assert Author.objects.get().name == "Ada"


@pytest.mark.django_db
def test_the_original_command_names_still_work(tmp_path):
    Author.objects.create(name="Grace")
    output = tmp_path / "legacy.dbs"

    call_command("dbs_backup", str(output), stdout=StringIO(), **FAST)
    call_command("dbs_validate", str(output), stdout=StringIO())
    Author.objects.all().delete()
    call_command("dbs_restore", str(output), stdout=StringIO())

    assert Author.objects.get().name == "Grace"


@pytest.mark.django_db
def test_the_umbrella_and_the_original_agree(tmp_path):
    Author.objects.create(name="Linus")
    umbrella = tmp_path / "a.dbs"
    original = tmp_path / "b.dbs"

    call_command("dbs", "backup", str(umbrella), stdout=StringIO(), **FAST)
    call_command("dbs_backup", str(original), stdout=StringIO(), **FAST)

    assert umbrella.read_bytes()[:8] == original.read_bytes()[:8] == b"DBSCON01"


@pytest.mark.django_db
def test_a_dry_run_through_the_umbrella_changes_nothing(tmp_path):
    Author.objects.create(name="Ada")
    output = tmp_path / "dry.dbs"
    call_command("dbs", "backup", str(output), stdout=StringIO(), **FAST)
    Author.objects.all().delete()
    out = StringIO()

    call_command("dbs", "restore", str(output), dry_run=True, stdout=out)

    assert "Dry run" in out.getvalue()
    assert not Author.objects.exists()
