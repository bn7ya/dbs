"""The manage.py dbs umbrella, its django-dbs alias and the original command names."""

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


def test_the_hyphenated_alias_loads_the_underscore_module():
    assert load_command_class("dbs", "django-dbs").__module__.endswith("django_dbs")


def test_bare_dbs_prints_an_overview():
    out = StringIO()

    call_command("dbs", stdout=out)

    printed = out.getvalue()
    assert "/admin/dbs/" in printed
    assert "dbs ai" in printed
    for name in SUBCOMMANDS:
        assert f"manage.py dbs {name}" in printed


def test_django_dbs_works_and_points_at_the_shorter_name():
    out = StringIO()

    call_command("django-dbs", stdout=out)

    assert 'also available as "manage.py dbs"' in out.getvalue()
    assert "manage.py dbs backup" in out.getvalue()


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
