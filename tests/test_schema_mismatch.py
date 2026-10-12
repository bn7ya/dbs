import io
from io import StringIO

import pytest
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections
from django.test import Client

from dbs.engine import backup as backup_engine
from dbs.engine import create_backup, restore_backup
from dbs.engine import restore as restore_engine
from dbs.exceptions import RestoreError
from dbs.models import AuditEvent
from dbs.notices import (
    FIELDS_LEFT_OUT,
    FIELDS_NOT_IN_BACKUP,
    FILES_LEFT_OUT,
    MODELS_LEFT_OUT,
)
from dbs.registry import BackupRegistry, FieldType, ModelBackup
from tests.complexapp.models import Writer
from tests.conftest import FAST_KDF
from tests.testapp.models import Author, Book, Tag

PASS = "schema-mismatch-pass-phrase"
RESTORE = "/admin/dbs/backuprecord/restore/"


def _registry(*models):
    registry = BackupRegistry()
    for model in models:
        registry.register(model)
    return registry


def _backup(monkeypatch, registry, edit=None):
    real = backup_engine.serialize_model

    def edited(model, *args):
        records = real(model, *args)
        return edit(model._meta.label_lower, records) if edit else records

    monkeypatch.setattr(backup_engine, "serialize_model", edited)
    try:
        return create_backup(PASS, registry=registry, kdf_params=FAST_KDF)
    finally:
        monkeypatch.setattr(backup_engine, "serialize_model", real)


def _warning(out, code):
    return next(warning.message for warning in out.warnings if warning.code == code)


def _with_retired_gadget(label, records):
    if label != "testapp.author":
        return records
    return records + [{"model": "retired.gadget", "pk": 1, "fields": {"name": "old"}}]


@pytest.mark.django_db
def test_a_model_the_project_lacks_refuses_the_restore(monkeypatch):
    Author.objects.create(name="Ada")
    container = _backup(monkeypatch, _registry(Author), _with_retired_gadget)
    Author.objects.all().delete()

    for dry_run in (True, False):
        with pytest.raises(RestoreError, match=r"retired\.gadget \(1 row\)"):
            restore_backup(container, PASS, dry_run=dry_run)

    assert not Author.objects.exists()


@pytest.mark.django_db
def test_allowing_missing_models_restores_everything_else(monkeypatch):
    Author.objects.create(name="Ada")
    container = _backup(monkeypatch, _registry(Author), _with_retired_gadget)
    Author.objects.all().delete()

    out = restore_backup(container, PASS, allow_missing_models=True)

    assert Author.objects.get().name == "Ada"
    assert out.records_loaded == 1
    assert out.skipped_models == ["retired.gadget"]
    assert _warning(out, MODELS_LEFT_OUT) == (
        "Left out retired.gadget (1 row), which this project does not have."
    )


@pytest.mark.django_db
def test_a_missing_table_is_refused_before_any_row_is_written(monkeypatch):
    author = Author.objects.create(name="Ada")
    Book.objects.create(title="Kept", author=author)
    container = _backup(monkeypatch, _registry(Author, Book))
    Book.objects.all().delete()
    Author.objects.all().delete()
    introspection = connections["default"].introspection
    real_names = introspection.table_names
    monkeypatch.setattr(
        introspection,
        "table_names",
        lambda *args, **kwargs: [
            name for name in real_names(*args, **kwargs) if name != "testapp_book"
        ],
    )

    with pytest.raises(RestoreError, match=r"no table for testapp\.book\. Run migrate"):
        restore_backup(container, PASS)

    assert not Author.objects.exists()


@pytest.mark.django_db
def test_a_field_the_project_lacks_is_reported(monkeypatch):
    Author.objects.create(name="Ada")

    def with_nickname(label, records):
        for record in records:
            record["fields"]["nickname"] = "Countess"
        return records

    container = _backup(monkeypatch, _registry(Author), with_nickname)
    Author.objects.all().delete()

    out = restore_backup(container, PASS)

    assert Author.objects.get().name == "Ada"
    assert _warning(out, FIELDS_LEFT_OUT) == (
        "testapp.author: nickname is in the backup but not in this project's model, "
        "so its values are left out."
    )


def _without_title_and_tags(label, records):
    if label == "testapp.book":
        for record in records:
            del record["fields"]["title"]
            del record["fields"]["tags"]
    return records


@pytest.mark.django_db
def test_merging_keeps_the_values_of_fields_the_backup_lacks(monkeypatch):
    ada = Author.objects.create(name="Ada")
    grace = Author.objects.create(name="Grace")
    python = Tag.objects.create(label="python")
    backup = Tag.objects.create(label="backup")
    kept = Book.objects.create(title="Original", author=ada)
    kept.tags.set([python, backup])
    gone = Book.objects.create(title="Gone", author=ada)
    container = _backup(
        monkeypatch, _registry(Author, Tag, Book), _without_title_and_tags
    )
    Book.objects.filter(pk=kept.pk).update(title="Edited here", author=grace)
    kept.tags.set([backup])
    gone_pk = gone.pk
    gone.delete()

    out = restore_backup(container, PASS)

    kept.refresh_from_db()
    assert kept.title == "Edited here"
    assert kept.author == ada
    assert list(kept.tags.values_list("label", flat=True)) == ["backup"]
    returned = Book.objects.get(pk=gone_pk)
    assert returned.title == ""
    assert returned.author == ada
    assert _warning(out, FIELDS_NOT_IN_BACKUP) == (
        "testapp.book: tags, title are not in the backup. Rows new to this database get "
        "their defaults; rows already here keep their values."
    )


@pytest.mark.django_db
def test_merging_keeps_a_field_left_out_on_purpose_without_a_warning(monkeypatch):
    class WithoutName(ModelBackup):
        overrides = {"name": FieldType.EXCLUDE}

    registry = BackupRegistry()
    registry.register(Author)(WithoutName)
    author = Author.objects.create(name="Ada")
    container = create_backup(PASS, registry=registry, kdf_params=FAST_KDF)
    monkeypatch.setattr("dbs.engine.schema.backup_registry", registry)

    out = restore_backup(container, PASS)

    author.refresh_from_db()
    assert author.name == "Ada"
    assert FIELDS_NOT_IN_BACKUP not in {warning.code for warning in out.warnings}


@pytest.mark.django_db
def test_replacing_gives_fields_the_backup_lacks_their_defaults(monkeypatch):
    ada = Author.objects.create(name="Ada")
    Book.objects.create(title="Original", author=ada)
    container = _backup(
        monkeypatch, _registry(Author, Tag, Book), _without_title_and_tags
    )

    out = restore_backup(container, PASS, flush=True)

    assert Book.objects.get().title == ""
    assert _warning(out, FIELDS_NOT_IN_BACKUP) == (
        "testapp.book: tags, title are not in the backup. Restored rows get their defaults."
    )


@pytest.mark.django_db
def test_a_file_with_no_field_to_land_in_is_left_out(tmp_path, settings, monkeypatch):
    settings.MEDIA_ROOT = str(tmp_path)
    book = Book.objects.create(title="Covered", author=Author.objects.create(name="Ada"))
    book.cover.save("cover.bin", ContentFile(b"COVER"))
    real_collect = backup_engine.collect_instance_files

    def renamed(*args):
        for entry, data in real_collect(*args):
            entry.field = "jacket"
            yield entry, data

    monkeypatch.setattr(backup_engine, "collect_instance_files", renamed)
    container = create_backup(PASS, registry=_registry(Author, Book), kdf_params=FAST_KDF)
    cover_path = tmp_path / book.cover.name
    cover_path.unlink()

    out = restore_backup(container, PASS)

    assert out.files_written == 0
    assert not cover_path.exists()
    assert _warning(out, FILES_LEFT_OUT) == (
        "Left out 1 file of testapp.book.jacket: this project's model has no file field "
        "by that name."
    )


@pytest.mark.django_db
def test_a_file_outside_the_restore_roots_stops_the_restore_before_any_row(
    tmp_path, settings
):
    sidecar = tmp_path / "outside" / "sidecar.dat"
    sidecar.parent.mkdir()
    sidecar.write_bytes(b"SIDECAR")
    settings.DBS_RESTORE_ROOTS = [str(tmp_path / "allowed")]
    Book.objects.create(
        title="Pointing out", author=Author.objects.create(name="Ada"), sidecar_path=str(sidecar)
    )
    container = create_backup(PASS, kdf_params=FAST_KDF)
    Book.objects.all().delete()
    Author.objects.all().delete()

    for dry_run in (True, False):
        with pytest.raises(RestoreError, match="Refusing to write"):
            restore_backup(container, PASS, dry_run=dry_run)

    assert not Author.objects.exists()
    assert not Book.objects.exists()


@pytest.mark.django_db
def test_a_unique_clash_names_the_row_and_changes_nothing(monkeypatch):
    Writer.objects.create(name_en="A", name_ar="A", penname="ghost")
    container = _backup(monkeypatch, _registry(Writer))
    Writer.objects.all().delete()
    Writer.objects.create(name_en="Z", name_ar="Z", penname="zed")
    Writer.objects.create(name_en="B", name_ar="B", penname="ghost")
    before = sorted(Writer.objects.values_list("pk", "penname"))

    with pytest.raises(RestoreError) as refused:
        restore_backup(container, PASS)

    message = str(refused.value)
    assert message.startswith("complexapp.writer 1 could not be written: ")
    assert "flush replaces them instead" in message
    assert message.endswith("Nothing was changed.")
    assert sorted(Writer.objects.values_list("pk", "penname")) == before

    restore_backup(container, PASS, flush=True)

    assert list(Writer.objects.values_list("pk", "penname")) == [(1, "ghost")]


@pytest.mark.django_db
def test_a_value_that_does_not_fit_the_field_is_refused(monkeypatch):
    Book.objects.create(title="Typed", author=Author.objects.create(name="Ada"))

    def with_bad_author(label, records):
        if label == "testapp.book":
            records[0]["fields"]["author"] = "not-a-number"
        return records

    container = _backup(monkeypatch, _registry(Author, Book), with_bad_author)
    Book.objects.all().delete()
    Author.objects.all().delete()

    with pytest.raises(RestoreError, match="does not fit this project's model") as refused:
        restore_backup(container, PASS)

    assert str(refused.value).endswith("Nothing was changed.")
    assert not Author.objects.exists()


@pytest.mark.django_db
def test_a_file_that_cannot_be_written_says_what_was_restored(tmp_path, settings, monkeypatch):
    settings.DBS_RESTORE_ROOTS = [str(tmp_path)]
    sidecar = tmp_path / "sidecar.dat"
    sidecar.write_bytes(b"SIDECAR")
    Book.objects.create(
        title="Half", author=Author.objects.create(name="Ada"), sidecar_path=str(sidecar)
    )
    container = create_backup(PASS, kdf_params=FAST_KDF)
    Book.objects.all().delete()
    Author.objects.all().delete()

    def disk_full(entry, data):
        raise OSError("No space left on device")

    monkeypatch.setattr(restore_engine, "restore_file", disk_full)

    with pytest.raises(RestoreError) as refused:
        restore_backup(container, PASS)

    assert str(refused.value) == (
        f"The rows were restored, but {sidecar} could not be written: No space left on "
        "device. 0 of 1 files were written."
    )
    assert Book.objects.get().title == "Half"


@pytest.mark.django_db
def test_the_command_refuses_a_missing_model_unless_allowed(tmp_path, monkeypatch):
    Author.objects.create(name="Ada")
    path = tmp_path / "gadget.dbs"
    path.write_bytes(_backup(monkeypatch, _registry(Author), _with_retired_gadget))
    Author.objects.all().delete()

    with pytest.raises(CommandError, match=r"Restore failed: The backup holds data .*gadget"):
        call_command("dbs_restore", str(path), passphrase=PASS, stdout=StringIO())

    out = StringIO()
    call_command(
        "dbs", "restore", str(path), "--allow-missing-models", "--passphrase", PASS, stdout=out
    )

    text = out.getvalue()
    assert "Warning [models_left_out]: Left out retired.gadget (1 row)" in text
    assert "Restored 1 records and 0 files." in text
    event = AuditEvent.objects.filter(action="backup.restore", succeeded=True).get()
    assert event.data["skipped_models"] == ["retired.gadget"]
    assert event.data["allow_missing_models"] is True


@pytest.mark.django_db
def test_the_command_reports_a_refused_row_without_a_traceback(tmp_path, monkeypatch):
    Writer.objects.create(name_en="A", name_ar="A", penname="ghost")
    path = tmp_path / "writers.dbs"
    path.write_bytes(_backup(monkeypatch, _registry(Writer)))
    Writer.objects.all().delete()
    Writer.objects.create(name_en="B", name_ar="B", penname="ghost")

    with pytest.raises(CommandError, match="Restore failed: complexapp.writer 1 could not"):
        call_command("dbs_restore", str(path), passphrase=PASS, stdout=StringIO())

    assert AuditEvent.objects.filter(action="backup.restore", succeeded=False).exists()


@pytest.fixture
def panel(db):
    user = User.objects.create_superuser("root", "root@example.com", "pw")
    client = Client()
    client.force_login(user)
    client.post(
        "/admin/dbs/panel/setup/",
        {
            "level": "relaxed",
            "expected_networks": "",
            "trusted_networks": "127.0.0.0/8",
            "notify_emails": "",
        },
    )
    return client


def _upload(container):
    upload = io.BytesIO(container)
    upload.name = "backup.dbs"
    return upload


def test_the_panel_reports_a_refused_row_instead_of_failing(panel, monkeypatch):
    Writer.objects.create(name_en="A", name_ar="A", penname="ghost")
    container = _backup(monkeypatch, _registry(Writer))
    Writer.objects.all().delete()
    Writer.objects.create(name_en="B", name_ar="B", penname="ghost")

    response = panel.post(
        RESTORE, {"backup": _upload(container), "passphrase": PASS}, follow=True
    )

    assert response.status_code == 200
    assert b"Restore failed: complexapp.writer 1 could not be written" in response.content
    assert AuditEvent.objects.filter(action="backup.restore", succeeded=False).exists()


def test_the_panel_allows_missing_models_and_shows_the_warnings(panel, monkeypatch):
    Author.objects.create(name="Ada")
    container = _backup(monkeypatch, _registry(Author), _with_retired_gadget)

    refused = panel.post(
        RESTORE, {"backup": _upload(container), "passphrase": PASS}, follow=True
    )
    allowed = panel.post(
        RESTORE,
        {"backup": _upload(container), "passphrase": PASS, "allow_missing_models": "on"},
        follow=True,
    )

    assert b"Restore failed: The backup holds data" in refused.content
    assert b"Restored 1 records" in allowed.content
    assert b"Left out retired.gadget (1 row)" in allowed.content
    assert b"already holds rows for testapp.author" in allowed.content
