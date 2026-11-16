"""A backup records the application it belongs to, and a restore refuses another's."""

import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from dbs import connection, create_backup, identity, restore_backup, upgrade, validate_backup
from dbs.engine.frames import checked_header
from dbs.exceptions import ContainerError, ForeignBackup, RestoreError
from dbs.upgrade import OK, WARN
from tests.conftest import FAST_KDF
from tests.payloads import container_of, header_of
from tests.testapp.models import Author

PASS = "identity-passphrase"
STABILITY = Path(__file__).parent / "stability"


def backup(**options):
    return create_backup(PASS, kdf_params=FAST_KDF, **options)


def test_an_application_is_named_after_its_project_package(settings):
    assert identity.application_name() == "tests"

    settings.ROOT_URLCONF = "shop.urls"
    assert identity.application_name() == "shop"

    settings.ROOT_URLCONF = "urls"
    assert identity.application_name() == "urls"


def test_the_setting_names_it_instead(settings):
    settings.DBS_APPLICATION = "shop-production"

    assert identity.application_name() == "shop-production"
    assert identity.is_named_by_setting()


def test_a_project_without_a_urlconf_is_named_after_its_settings_module(settings):
    del settings.ROOT_URLCONF

    assert identity.application_name() == "tests"


@pytest.mark.django_db
def test_every_backup_records_its_application(settings):
    settings.DBS_APPLICATION = "shop"

    assert header_of(backup(), PASS)["application"] == "shop"


@pytest.mark.django_db
def test_a_backup_restores_in_the_application_that_wrote_it(committed):
    Author.objects.create(name="Ada")
    container = backup()
    Author.objects.all().delete()

    with committed():
        restore_backup(container, PASS)

    assert Author.objects.get().name == "Ada"


@pytest.mark.django_db
@pytest.mark.parametrize("dry_run", [True, False])
def test_a_backup_of_another_application_is_refused_before_anything_loads(
    settings, committed, dry_run
):
    Author.objects.create(name="Ada")
    settings.DBS_APPLICATION = "shop"
    container = backup()
    Author.objects.all().delete()
    settings.DBS_APPLICATION = "depot"

    with pytest.raises(ForeignBackup) as refused, committed():
        restore_backup(container, PASS, dry_run=dry_run)

    assert isinstance(refused.value, RestoreError)
    assert "belongs to the application 'shop'" in str(refused.value)
    assert "this project is 'depot'" in str(refused.value)
    assert "--another-application" in str(refused.value)
    assert not Author.objects.exists()


@pytest.mark.django_db
def test_it_is_refused_in_both_directions(settings):
    settings.DBS_APPLICATION = "depot"
    theirs = backup()
    settings.DBS_APPLICATION = "shop"
    ours = backup()

    with pytest.raises(ForeignBackup):
        restore_backup(theirs, PASS, dry_run=True)
    settings.DBS_APPLICATION = "depot"
    with pytest.raises(ForeignBackup):
        restore_backup(ours, PASS, dry_run=True)


@pytest.mark.django_db
def test_saying_it_is_another_applications_loads_it(settings, committed):
    Author.objects.create(name="Ada")
    settings.DBS_APPLICATION = "shop"
    container = backup()
    Author.objects.all().delete()
    settings.DBS_APPLICATION = "depot"

    with committed():
        restore_backup(container, PASS, another_application=True)

    assert Author.objects.get().name == "Ada"


@pytest.mark.django_db
def test_a_shared_name_does_not_pass_a_backup_that_holds_none_of_this_projects_models(
    settings,
):
    container = container_of(
        {"order": ["auth.user", "ledger.entry", "ledger.account"], "application": "tests"},
        PASS,
    )

    with pytest.raises(ForeignBackup) as refused:
        restore_backup(container, PASS, dry_run=True)

    assert "none of the models it holds (ledger.entry, ledger.account)" in str(refused.value)


@pytest.mark.django_db
def test_a_backup_that_shares_a_model_with_this_project_is_its_own():
    container = container_of(
        {"order": ["testapp.author", "ledger.entry"], "application": "tests"}, PASS
    )

    restore_backup(container, PASS, dry_run=True)


@pytest.mark.django_db
def test_a_backup_that_holds_only_what_django_ships_is_told_apart_by_name_alone(settings):
    same = container_of({"order": ["auth.user", "auth.group"], "application": "tests"}, PASS)
    other = container_of({"order": ["auth.user", "auth.group"], "application": "depot"}, PASS)

    restore_backup(same, PASS, dry_run=True)
    with pytest.raises(ForeignBackup):
        restore_backup(other, PASS, dry_run=True)


@pytest.mark.django_db
def test_a_backup_that_records_no_application_restores_as_before():
    container = container_of({"order": ["ledger.entry"]}, PASS)

    restore_backup(container, PASS, dry_run=True)


@pytest.mark.django_db
@pytest.mark.parametrize("release", ["0.8.0", "0.8.3"])
def test_a_backup_from_before_applications_were_recorded_still_restores(
    release, settings, tmp_path, committed
):
    promised = json.loads((STABILITY / release / "library.json").read_text())["backup"]
    settings.DBS_APPLICATION = "some-other-name"
    settings.MEDIA_ROOT = str(tmp_path / "media")
    settings.DBS_RESTORE_ROOTS = [str(tmp_path)]

    with committed():
        result = restore_backup(str(STABILITY / release / "backup.dbs"), promised["passphrase"])

    assert result.records_loaded == promised["records"]


def test_a_header_whose_application_is_not_text_is_malformed():
    with pytest.raises(ContainerError):
        checked_header({"version": 2, "order": [], "application": ["shop"]})

    assert checked_header({"version": 2, "order": [], "application": "shop"})


@pytest.mark.django_db
def test_validation_names_the_application(settings):
    settings.DBS_APPLICATION = "shop"
    container = backup()

    result = validate_backup(container, PASS)

    assert result.ok and result.application == "shop"
    assert "Application: shop" in result.summary()
    assert validate_backup(container).application == ""


@pytest.mark.django_db
def test_the_restore_command_refuses_and_takes_the_flag(settings, tmp_path, committed):
    Author.objects.create(name="Ada")
    settings.DBS_APPLICATION = "shop"
    path = tmp_path / "shop.dbs"
    path.write_bytes(backup())
    Author.objects.all().delete()
    settings.DBS_APPLICATION = "depot"

    with pytest.raises(CommandError) as refused:
        call_command("dbs_restore", str(path), "--passphrase", PASS, stdout=StringIO())
    with committed():
        call_command(
            "dbs_restore", str(path), "--passphrase", PASS, "--another-application",
            stdout=StringIO(),
        )

    assert "belongs to the application 'shop'" in str(refused.value)
    assert Author.objects.get().name == "Ada"


@pytest.mark.django_db
def test_a_refusal_is_recorded_with_its_own_error_code(settings, tmp_path):
    from dbs.models import AuditEvent

    settings.DBS_APPLICATION = "shop"
    path = tmp_path / "shop.dbs"
    path.write_bytes(backup())
    settings.DBS_APPLICATION = "depot"

    with pytest.raises(CommandError):
        call_command("dbs_restore", str(path), "--passphrase", PASS, stdout=StringIO())

    entry = AuditEvent.objects.filter(action="backup.restore").first()
    assert (entry.status, entry.error_code) == ("failed", "ForeignBackup")


def test_connection_details_name_the_application(settings):
    settings.DBS_APPLICATION = "shop"

    assert connection.details()["application"] == "shop"


def test_upgrade_says_which_application_backups_record(settings):
    named = upgrade.ApplicationName().check()

    assert named.level == OK and "'tests'" in named.message
    assert upgrade.ApplicationName in upgrade.STEPS


@pytest.mark.parametrize("package", ["config", "core", "mysite", "Project"])
def test_upgrade_warns_about_a_name_other_projects_share(settings, package):
    settings.ROOT_URLCONF = f"{package}.urls"

    shared = upgrade.ApplicationName().check()
    settings.DBS_APPLICATION = package
    chosen = upgrade.ApplicationName().check()

    assert shared.level == WARN and "DBS_APPLICATION" in shared.remedy
    assert chosen.level == OK


def test_upgrade_warns_when_nothing_names_the_application(settings, monkeypatch):
    monkeypatch.setattr(identity, "application_name", lambda: "")

    assert upgrade.ApplicationName().check().level == WARN
