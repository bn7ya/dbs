"""End-to-end backup/restore, corruption healing, and security checks."""

import logging
import os

import pytest
from django.contrib.sessions.models import Session
from django.core.files.base import ContentFile
from django.db import connections

from dbs.container.format import copy_offsets
from dbs.engine import backup as backup_engine
from dbs.engine import restore as restore_engine
from dbs.engine import create_backup, restore_backup, validate_backup
from dbs.exceptions import CorruptionError, InvalidPassphrase
from dbs.introspect import DEFAULT_EXCLUDES, _excluded_labels, discover_models
from dbs.registry import BackupRegistry
from tests.conftest import FAST_KDF
from tests.testapp.models import Author, Book, Tag

PASS = "test-pass-phrase"

COVER_BYTES = b"COVER-BYTES-\x00\x01\x02\xff"
SIDECAR_BYTES = b"SIDECAR-CONTENT-9999"


def _make_sample(tmp_path):
    author = Author.objects.create(name="Ada")
    t1 = Tag.objects.create(label="python")
    t2 = Tag.objects.create(label="backup")
    book = Book.objects.create(title="Resilient Data", author=author)
    book.tags.set([t1, t2])
    book.cover.save("cover.bin", ContentFile(COVER_BYTES), save=True)

    sidecar = tmp_path / "sidecar.dat"
    sidecar.write_bytes(SIDECAR_BYTES)
    book.sidecar_path = str(sidecar)
    book.save()
    return book, sidecar


def _wipe(book, sidecar):
    cover_path = book.cover.storage.path(book.cover.name)
    Book.objects.all().delete()
    Tag.objects.all().delete()
    Author.objects.all().delete()
    if os.path.exists(cover_path):
        os.remove(cover_path)
    if sidecar.exists():
        sidecar.unlink()


@pytest.mark.django_db
def test_backup_restore_roundtrip(tmp_path, settings):
    settings.DBS_RESTORE_ROOTS = [str(tmp_path)]
    book, sidecar = _make_sample(tmp_path)
    cover_name = book.cover.name

    container = create_backup(PASS, kdf_params=FAST_KDF)

    result = validate_backup(container, PASS)
    assert result.ok and result.decrypted_ok

    _wipe(book, sidecar)
    assert not Book.objects.exists()

    out = restore_backup(container, PASS)
    assert out.records_loaded >= 4  # author + 2 tags + book
    assert out.files_written == 2   # cover + sidecar

    restored = Book.objects.get(title="Resilient Data")
    assert restored.author.name == "Ada"
    assert set(restored.tags.values_list("label", flat=True)) == {"python", "backup"}
    assert restored.cover.name == cover_name
    with restored.cover.storage.open(restored.cover.name, "rb") as fh:
        assert fh.read() == COVER_BYTES
    assert sidecar.read_bytes() == SIDECAR_BYTES


@pytest.mark.django_db
def test_restore_heals_corruption_in_one_copy(tmp_path, settings):
    settings.DBS_RESTORE_ROOTS = [str(tmp_path)]
    book, sidecar = _make_sample(tmp_path)
    container = create_backup(PASS, kdf_params=FAST_KDF)

    a_off, _b_off, copy_len = copy_offsets(container)
    damaged = bytearray(container)
    # Obliterate the start of copy A so Reed-Solomon alone can't save it; the
    # engine must fall back to copy B.
    wipe = min(copy_len, 4000)
    damaged[a_off : a_off + wipe] = b"\x00" * wipe

    _wipe(book, sidecar)
    out = restore_backup(bytes(damaged), PASS)
    assert out.healed
    assert Book.objects.filter(title="Resilient Data").exists()
    assert sidecar.read_bytes() == SIDECAR_BYTES


@pytest.mark.django_db
def test_restore_survives_truncation_that_destroys_copy_b(tmp_path, settings):
    settings.DBS_RESTORE_ROOTS = [str(tmp_path)]
    book, sidecar = _make_sample(tmp_path)
    container = create_backup(PASS, kdf_params=FAST_KDF)
    _a_off, b_off, _copy_len = copy_offsets(container)
    truncated = container[:b_off]

    result = validate_backup(truncated)
    assert result.ok
    assert result.repair_report.copies_available == 1
    assert result.repair_report.healed

    _wipe(book, sidecar)
    out = restore_backup(truncated, PASS)
    assert out.healed
    assert Book.objects.filter(title="Resilient Data").exists()
    assert sidecar.read_bytes() == SIDECAR_BYTES


@pytest.mark.django_db
def test_unrecoverable_corruption_raises_and_loads_nothing(tmp_path):
    book, sidecar = _make_sample(tmp_path)
    container = create_backup(PASS, kdf_params=FAST_KDF)
    a_off, b_off, copy_len = copy_offsets(container)

    damaged = bytearray(container)
    damaged[a_off : a_off + copy_len] = b"\x00" * copy_len  # destroy copy A
    damaged[b_off : b_off + copy_len] = b"\x01" * copy_len  # destroy copy B

    _wipe(book, sidecar)
    with pytest.raises(CorruptionError):
        restore_backup(bytes(damaged), PASS)
    assert not Book.objects.exists()  # nothing partially restored


@pytest.mark.django_db
def test_wrong_passphrase_rejected(tmp_path):
    _make_sample(tmp_path)
    container = create_backup(PASS, kdf_params=FAST_KDF)
    with pytest.raises(InvalidPassphrase):
        restore_backup(container, "definitely-not-it")


@pytest.mark.django_db
def test_passphrase_never_appears_in_container(tmp_path):
    _make_sample(tmp_path)
    container = create_backup(PASS, kdf_params=FAST_KDF)
    assert PASS.encode() not in container


@pytest.mark.django_db
def test_validate_reports_corruption_without_passphrase(tmp_path):
    _make_sample(tmp_path)
    container = create_backup(PASS, kdf_params=FAST_KDF)
    a_off, b_off, copy_len = copy_offsets(container)
    damaged = bytearray(container)
    damaged[a_off : a_off + copy_len] = b"\x00" * copy_len
    damaged[b_off : b_off + copy_len] = b"\x01" * copy_len
    result = validate_backup(bytes(damaged))  # no passphrase needed
    assert not result.ok


def test_default_excludes_apply_when_setting_unset():
    assert _excluded_labels() == DEFAULT_EXCLUDES
    discovered = discover_models(BackupRegistry())
    assert Session not in discovered


def test_exclude_models_setting_extends_defaults(settings):
    settings.DBS_EXCLUDE_MODELS = ["testapp.Tag"]
    assert _excluded_labels() == DEFAULT_EXCLUDES | {"testapp.tag"}
    discovered = discover_models(BackupRegistry())
    assert Tag not in discovered
    assert Session not in discovered


def test_minus_prefix_reincludes_default_excluded_model(settings):
    settings.DBS_EXCLUDE_MODELS = ["-sessions.Session"]
    excluded = _excluded_labels()
    assert "sessions.session" not in excluded
    assert DEFAULT_EXCLUDES - {"sessions.session"} <= excluded
    discovered = discover_models(BackupRegistry())
    assert Session in discovered


def test_exclude_labels_match_case_insensitively(settings):
    settings.DBS_EXCLUDE_MODELS = ["TestApp.TAG", "-SESSIONS.Session"]
    excluded = _excluded_labels()
    assert "testapp.tag" in excluded
    assert "sessions.session" not in excluded


@pytest.mark.django_db
def test_dry_run_reports_counts_and_changes_nothing(tmp_path, settings):
    settings.DBS_RESTORE_ROOTS = [str(tmp_path)]
    book, sidecar = _make_sample(tmp_path)
    cover_path = book.cover.storage.path(book.cover.name)
    container = create_backup(PASS, kdf_params=FAST_KDF)
    _wipe(book, sidecar)

    out = restore_backup(container, PASS, dry_run=True)

    assert out.records_would_load >= 4
    assert out.files_would_write == 2
    assert out.records_loaded == 0
    assert out.files_written == 0
    assert not Author.objects.exists()
    assert not Book.objects.exists()
    assert not Tag.objects.exists()
    assert not os.path.exists(cover_path)
    assert not sidecar.exists()


@pytest.mark.django_db
def test_dry_run_on_populated_target_reports_preexisting_models(tmp_path, settings):
    settings.DBS_RESTORE_ROOTS = [str(tmp_path)]
    _make_sample(tmp_path)
    container = create_backup(PASS, kdf_params=FAST_KDF)
    Author.objects.create(name="Post Backup")

    out = restore_backup(container, PASS, dry_run=True)

    assert "testapp.author" in out.preexisting_models
    assert out.records_would_load >= 4
    assert Author.objects.filter(name="Post Backup").exists()


@pytest.mark.django_db
def test_flush_replaces_instead_of_merging(tmp_path, settings):
    settings.DBS_RESTORE_ROOTS = [str(tmp_path)]
    _make_sample(tmp_path)
    container = create_backup(PASS, kdf_params=FAST_KDF)
    Author.objects.create(name="Post Backup")
    Tag.objects.create(label="later")

    out = restore_backup(container, PASS, flush=True)

    assert out.records_flushed >= 6
    assert out.records_loaded >= 4
    assert not Author.objects.filter(name="Post Backup").exists()
    assert not Tag.objects.filter(label="later").exists()
    assert Author.objects.count() == 1
    restored = Book.objects.get(title="Resilient Data")
    assert set(restored.tags.values_list("label", flat=True)) == {"python", "backup"}


@pytest.mark.django_db
def test_default_merge_keeps_post_backup_rows_and_warns(tmp_path, settings, caplog):
    settings.DBS_RESTORE_ROOTS = [str(tmp_path)]
    _make_sample(tmp_path)
    container = create_backup(PASS, kdf_params=FAST_KDF)
    extra = Author.objects.create(name="Post Backup")

    with caplog.at_level(logging.WARNING, logger="dbs"):
        out = restore_backup(container, PASS)

    assert Author.objects.filter(pk=extra.pk, name="Post Backup").exists()
    assert Author.objects.filter(name="Ada").exists()
    assert "testapp.author" in out.preexisting_models
    warning = next(
        record.getMessage()
        for record in caplog.records
        if "already holds rows" in record.getMessage()
    )
    assert "testapp.author" in warning


@pytest.mark.django_db
def test_matching_migration_state_restores_without_drift_warning(tmp_path, settings, caplog):
    settings.DBS_RESTORE_ROOTS = [str(tmp_path)]
    book, sidecar = _make_sample(tmp_path)
    container = create_backup(PASS, kdf_params=FAST_KDF)
    _wipe(book, sidecar)

    with caplog.at_level(logging.WARNING, logger="dbs"):
        out = restore_backup(container, PASS)

    assert out.records_loaded >= 4
    messages = [record.getMessage() for record in caplog.records]
    assert not [message for message in messages if "drift" in message]
    assert not [message for message in messages if "Django" in message]


@pytest.mark.django_db
def test_backup_ahead_migration_state_warns(tmp_path, monkeypatch, caplog):
    _make_sample(tmp_path)
    real_state = backup_engine.migration_state(connections["default"])
    monkeypatch.setattr(
        backup_engine,
        "migration_state",
        lambda connection: {**real_state, "futureapp": "0001_initial"},
    )
    container = create_backup(PASS, kdf_params=FAST_KDF)

    with caplog.at_level(logging.WARNING, logger="dbs"):
        restore_backup(container, PASS, dry_run=True)

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "drift" in message and "futureapp" in message and "newer schema" in message
        for message in messages
    )
    assert not any("schema is newer than" in message for message in messages)


@pytest.mark.django_db
def test_target_ahead_migration_state_warns(tmp_path, monkeypatch, caplog):
    _make_sample(tmp_path)
    real_state = backup_engine.migration_state(connections["default"])
    assert real_state
    stale_app = sorted(real_state)[0]
    stale = {app: name for app, name in real_state.items() if app != stale_app}
    monkeypatch.setattr(backup_engine, "migration_state", lambda connection: stale)
    container = create_backup(PASS, kdf_params=FAST_KDF)
    monkeypatch.undo()

    with caplog.at_level(logging.WARNING, logger="dbs"):
        restore_backup(container, PASS, dry_run=True)

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "drift" in message and stale_app in message and "schema is newer" in message
        for message in messages
    )


@pytest.mark.django_db
def test_backup_without_migration_state_restores_without_warning(tmp_path, settings, monkeypatch, caplog):
    settings.DBS_RESTORE_ROOTS = [str(tmp_path)]
    book, sidecar = _make_sample(tmp_path)
    container = create_backup(PASS, kdf_params=FAST_KDF)
    _wipe(book, sidecar)

    real_read = restore_engine.read_payload

    def read_pre_migration_metadata(data, passphrase):
        result = real_read(data, passphrase)
        result.document.pop("migrations", None)
        return result

    monkeypatch.setattr(restore_engine, "read_payload", read_pre_migration_metadata)

    with caplog.at_level(logging.WARNING, logger="dbs"):
        out = restore_backup(container, PASS)

    assert out.records_loaded >= 4
    assert Book.objects.filter(title="Resilient Data").exists()
    assert not [
        record for record in caplog.records if "drift" in record.getMessage()
    ]


def test_django_version_difference_is_reported(caplog):
    with caplog.at_level(logging.WARNING, logger="dbs"):
        restore_engine._warn_on_environment_drift({"django_version": "1.0"}, None)
    assert any(
        "Django 1.0" in record.getMessage() for record in caplog.records
    )
