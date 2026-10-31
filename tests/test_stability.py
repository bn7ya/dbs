"""Every release from 0.8.0 on keeps what it promised: its API, commands, settings and backups."""

from datetime import datetime
from importlib import metadata
from pathlib import Path

import pytest
from django.test.utils import override_settings

from dbs import BackupRegistry, restore_backup, validate_backup
from dbs.audit import link
from dbs.connection import details
from dbs.crypto.secrets import decrypt_secret
from dbs.health import report
from dbs.keys import default_passphrase
from dbs.models import AuditEvent
from tests.stability import (
    command_surface,
    destructive_migrations,
    documented_settings,
    missing,
    package_source,
    parser_changes,
    python_changes,
    python_surface,
    recorded,
    released_migrations_missing,
    releases,
)
from tests.testapp.dbs import BookBackup
from tests.testapp.models import Author, Book, Tag

RECORDED = [release for release in releases() if recorded(release, "library")]


@pytest.fixture(params=RECORDED, ids=lambda release: release.name)
def release(request):
    return request.param


@pytest.fixture
def promised(release):
    return recorded(release, "library")


def golden_registry():
    registry = BackupRegistry()
    registry.register(Author)
    registry.register(Tag)
    registry.register(Book)(BookBackup)
    return registry


def restored(media_root):
    return {
        "authors": sorted(Author.objects.values_list("name", flat=True)),
        "tags": sorted(Tag.objects.values_list("label", flat=True)),
        "books": sorted(
            (
                {
                    "title": book.title,
                    "author": book.author.name,
                    "tags": sorted(book.tags.values_list("label", flat=True)),
                    "cover": book.cover.name or "",
                    "cover_text": (Path(media_root) / book.cover.name).read_text(encoding="utf-8")
                    if book.cover.name
                    else None,
                }
                for book in Book.objects.select_related("author")
            ),
            key=lambda book: book["title"],
        ),
    }


def expected(backup):
    return {
        "authors": backup["authors"],
        "tags": backup["tags"],
        "books": sorted(backup["books"], key=lambda book: book["title"]),
    }


def test_0_8_0_is_recorded():
    assert "0.8.0" in [release.name for release in RECORDED]


def test_the_python_api_keeps_every_name_parameter_and_default(promised):
    assert python_changes(promised["python"], python_surface()) == []


def test_every_command_keeps_its_name_options_and_arguments(promised):
    surface = command_surface()

    assert missing(promised["commands"]["names"], surface["names"], "manage.py command") == []
    assert parser_changes("manage.py dbs", promised["commands"]["tree"], surface["tree"]) == []


@pytest.mark.django_db
def test_json_outputs_keep_every_key(promised):
    outputs = promised["outputs"]

    assert missing(outputs["connection --json"], details(), "connection --json key") == []
    assert missing(outputs["health --json"], report().as_dict(), "health --json key") == []


def test_every_setting_is_still_read_and_keeps_its_documented_default(promised):
    source = package_source()
    documented = documented_settings()

    for name, default in promised["settings"].items():
        assert f'"{name}"' in source, f"{name} is no longer read"
        assert documented.get(name) == default, f"{name} changed its default from {default}"


def test_released_migrations_stay_and_later_ones_drop_no_data(promised):
    for app_label, names in promised["migrations"].items():
        assert released_migrations_missing(app_label, names) == []
        assert destructive_migrations(app_label, names) == []


def test_console_scripts_and_install_extras_stay(promised):
    distribution = metadata.distribution("django-dbs")
    scripts = [entry.name for entry in distribution.entry_points if entry.group == "console_scripts"]
    extras = distribution.metadata.get_all("Provides-Extra") or []

    assert missing(promised["console_scripts"], scripts, "console script") == []
    assert missing(promised["extras"], extras, "install extra") == []


def test_the_passphrase_derived_from_secret_key_never_changes(promised):
    vectors = promised["vectors"]

    with override_settings(SECRET_KEY=vectors["secret_key"], SECRET_KEY_FALLBACKS=[]):
        assert default_passphrase() == vectors["default_passphrase"]


def test_a_stored_credential_still_opens(promised):
    vectors = promised["vectors"]

    with override_settings(SECRET_KEY=vectors["secret_key"], SECRET_KEY_FALLBACKS=[]):
        assert decrypt_secret(vectors["field_secret"]["token"]) == vectors["field_secret"]["plaintext"]


def test_a_recorded_audit_chain_still_verifies(promised):
    previous = ""
    for event in promised["vectors"]["audit_chain"]:
        fields = {
            name: datetime.fromisoformat(value) if name.endswith("_at") and value else value
            for name, value in event.items()
            if name != "chain_hash"
        }

        assert link(previous, AuditEvent(**fields)) == event["chain_hash"]
        previous = event["chain_hash"]


def test_the_golden_backup_still_validates(release, promised):
    backup = promised["backup"]

    result = validate_backup(str(release / backup["file"]), backup["passphrase"])

    assert result.ok, result.messages


@pytest.mark.django_db
def test_the_golden_backup_restores_every_row_and_file(release, promised, tmp_path, settings, committed):
    backup = promised["backup"]
    settings.MEDIA_ROOT = str(tmp_path / "media")

    with committed():
        restore_backup(str(release / backup["file"]), backup["passphrase"], registry=golden_registry())

    assert restored(settings.MEDIA_ROOT) == expected(backup)


@pytest.mark.django_db
def test_a_damaged_golden_backup_heals_and_restores(release, promised, tmp_path, settings, committed):
    backup = promised["backup"]
    settings.MEDIA_ROOT = str(tmp_path / "media")
    damaged = bytearray((release / backup["file"]).read_bytes())
    for start, length in backup["damage"]:
        damaged[start : start + length] = bytes(length)

    with committed():
        restore_backup(bytes(damaged), backup["passphrase"], registry=golden_registry())

    assert restored(settings.MEDIA_ROOT) == expected(backup)
