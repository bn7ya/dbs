"""End-to-end backup/restore, corruption healing, and security checks."""

import os

import pytest
from django.core.files.base import ContentFile

from dbs.container.format import copy_offsets
from dbs.engine import create_backup, restore_backup, validate_backup
from dbs.exceptions import CorruptionError, InvalidPassphrase
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
def test_backup_restore_roundtrip(tmp_path):
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
def test_restore_heals_corruption_in_one_copy(tmp_path):
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
