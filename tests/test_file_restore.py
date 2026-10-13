from io import StringIO

import pytest
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError

from dbs import ModelBackup
from dbs.engine import create_backup, restore_backup
from dbs.exceptions import ConfigurationError, RestoreError
from dbs.files import FileEntry, _sha256, plan_restore
from dbs.registry import BackupRegistry
from dbs.serialize import RowLoader
from tests.conftest import FAST_KDF
from tests.format1 import as_format1
from tests.testapp.dbs import BookBackup
from tests.testapp.models import Author, Book

PASS = "file-restore-pass-phrase"

FAST = {"kdf_time": 1, "kdf_memory": 8192}


def _books(*, assets=None):
    class AuthorAssets(ModelBackup):
        file_roots = [str(assets)] if assets else []

    registry = BackupRegistry()
    registry.register(Author)(AuthorAssets)
    registry.register(Book)(BookBackup)
    return registry


def _staging_files(directory):
    return [path for path in directory.rglob("*") if path.name.endswith(".dbs-restore")]


@pytest.fixture
def sidecar_book(db, tmp_path):
    sidecar = tmp_path / "old" / "sidecar.dat"
    sidecar.parent.mkdir()
    sidecar.write_bytes(b"SIDECAR")
    author = Author.objects.create(name="Ada")
    book = Book.objects.create(title="Notes", author=author, sidecar_path=str(sidecar))
    return book, sidecar


def _wipe_books():
    Book.objects.all().delete()
    Author.objects.all().delete()


@pytest.mark.django_db
def test_a_model_backups_own_file_roots_are_restore_roots(tmp_path, committed):
    assets = tmp_path / "assets"
    (assets / "logos").mkdir(parents=True)
    (assets / "logos" / "mark.svg").write_bytes(b"<svg/>")
    Author.objects.create(name="Ada")
    registry = _books(assets=assets)
    container = create_backup(PASS, registry=registry, kdf_params=FAST_KDF)
    (assets / "logos" / "mark.svg").unlink()

    with committed():
        out = restore_backup(container, PASS, registry=registry)

    assert (assets / "logos" / "mark.svg").read_bytes() == b"<svg/>"
    assert out.files_written == 1


def test_a_refused_file_stops_the_restore_before_any_row(sidecar_book, tmp_path, settings):
    book, sidecar = sidecar_book
    settings.DBS_RESTORE_ROOTS = [str(tmp_path / "elsewhere")]
    container = create_backup(PASS, registry=_books(), kdf_params=FAST_KDF)
    _wipe_books()

    with pytest.raises(RestoreError) as refused:
        restore_backup(container, PASS, registry=_books())

    assert str(sidecar) in str(refused.value)
    assert not Author.objects.exists()
    assert not Book.objects.exists()
    assert _staging_files(tmp_path) == []


def test_a_dry_run_reports_the_files_a_restore_would_refuse(sidecar_book, tmp_path, settings):
    book, sidecar = sidecar_book
    settings.DBS_RESTORE_ROOTS = [str(tmp_path / "elsewhere")]
    container = create_backup(PASS, registry=_books(), kdf_params=FAST_KDF)
    _wipe_books()

    out = restore_backup(container, PASS, dry_run=True, registry=_books())

    assert len(out.files_refused) == 1
    assert str(sidecar) in out.files_refused[0]
    assert out.files_would_write == 0
    assert out.records_would_load == 2
    assert not Author.objects.exists()


def test_the_dry_run_command_names_refused_files_and_fails(sidecar_book, tmp_path, settings):
    book, sidecar = sidecar_book
    settings.DBS_RESTORE_ROOTS = [str(tmp_path / "elsewhere")]
    backup_file = tmp_path / "refused.dbs"
    call_command("dbs_backup", str(backup_file), passphrase=PASS, stdout=StringIO(), **FAST)
    out = StringIO()

    with pytest.raises(CommandError) as failed:
        call_command("dbs", "restore", str(backup_file), passphrase=PASS, dry_run=True, stdout=out)

    assert "Would refuse" in out.getvalue()
    assert str(sidecar) in out.getvalue()
    assert "would stop before loading any row" in str(failed.value)


def test_files_wait_for_the_rows_to_commit(sidecar_book, tmp_path, settings, django_capture_on_commit_callbacks):
    book, sidecar = sidecar_book
    settings.DBS_RESTORE_ROOTS = [str(tmp_path)]
    container = create_backup(PASS, registry=_books(), kdf_params=FAST_KDF)
    _wipe_books()
    sidecar.unlink()

    with django_capture_on_commit_callbacks() as on_commit:
        out = restore_backup(container, PASS, registry=_books())

    assert not sidecar.exists()
    assert len(_staging_files(tmp_path)) == 1
    assert out.files_written == 0

    for callback in on_commit:
        callback()

    assert sidecar.read_bytes() == b"SIDECAR"
    assert _staging_files(tmp_path) == []
    assert out.files_written == 1


@pytest.mark.parametrize("form", [2, 1])
def test_a_failed_load_removes_the_staged_files(sidecar_book, tmp_path, settings, monkeypatch, form):
    book, sidecar = sidecar_book
    settings.DBS_RESTORE_ROOTS = [str(tmp_path)]
    container = create_backup(PASS, registry=_books(), kdf_params=FAST_KDF)
    if form == 1:
        container = as_format1(container, PASS)
    _wipe_books()
    sidecar.unlink()
    sidecar.parent.rmdir()

    def fail(self, records):
        raise RuntimeError("the load failed")

    monkeypatch.setattr(RowLoader, "save", fail)

    with pytest.raises(RuntimeError):
        restore_backup(container, PASS, registry=_books())

    assert not sidecar.parent.exists()
    assert _staging_files(tmp_path) == []


def test_a_path_map_moves_files_and_the_rows_that_name_them(
    sidecar_book, tmp_path, settings, committed
):
    book, sidecar = sidecar_book
    container = create_backup(PASS, registry=_books(), kdf_params=FAST_KDF)
    _wipe_books()
    sidecar.unlink()
    new_root = tmp_path / "new"
    settings.DBS_RESTORE_ROOTS = [str(new_root)]

    refused = restore_backup(container, PASS, dry_run=True, registry=_books())
    assert len(refused.files_refused) == 1

    settings.DBS_RESTORE_PATH_MAP = {str(tmp_path / "old"): str(new_root)}
    rehearsed = restore_backup(container, PASS, dry_run=True, registry=_books())
    assert rehearsed.files_refused == []
    assert rehearsed.files_would_write == 1

    with committed():
        restore_backup(container, PASS, registry=_books())

    moved = new_root / "sidecar.dat"
    assert moved.read_bytes() == b"SIDECAR"
    assert not sidecar.exists()
    assert Book.objects.get(pk=book.pk).sidecar_path == str(moved)


@pytest.mark.django_db
def test_a_path_map_moves_a_whole_file_root(tmp_path, settings, committed):
    old_root = tmp_path / "srv-a" / "uploads"
    (old_root / "2024").mkdir(parents=True)
    (old_root / "2024" / "report.pdf").write_bytes(b"%PDF")
    settings.DBS_FILE_ROOTS = [str(old_root)]
    Author.objects.create(name="Ada")
    container = create_backup(PASS, registry=_books(), kdf_params=FAST_KDF)
    new_root = tmp_path / "srv-b" / "uploads"
    settings.DBS_FILE_ROOTS = [str(new_root)]
    settings.DBS_RESTORE_PATH_MAP = {str(old_root): str(new_root)}

    with committed():
        restore_backup(container, PASS, registry=_books())

    assert (new_root / "2024" / "report.pdf").read_bytes() == b"%PDF"


def test_file_fields_land_in_the_current_storage_location(db, tmp_path, settings, committed):
    settings.MEDIA_ROOT = str(tmp_path / "media-a")
    author = Author.objects.create(name="Ada")
    book = Book.objects.create(title="Cover", author=author)
    book.cover.save("cover.bin", ContentFile(b"COVER"), save=True)
    container = create_backup(PASS, registry=_books(), kdf_params=FAST_KDF)
    settings.MEDIA_ROOT = str(tmp_path / "media-b")

    with committed():
        restore_backup(container, PASS, registry=_books())

    assert (tmp_path / "media-b" / book.cover.name).read_bytes() == b"COVER"


def test_a_storage_name_that_climbs_out_is_refused():
    data = b"payload"
    entry = FileEntry(
        kind="storage", size=len(data), sha256=_sha256(data),
        model="testapp.book", pk=1, field="cover", name="../../escape.bin",
    )

    placement = plan_restore([(entry, data)])[0]

    assert "outside the field's storage" in placement.problem


def test_a_malformed_path_map_is_reported(settings):
    settings.DBS_RESTORE_PATH_MAP = ["/old", "/new"]

    with pytest.raises(ConfigurationError):
        plan_restore([])
