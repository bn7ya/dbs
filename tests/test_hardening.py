"""Hardening checks: path confinement, KDF ceilings, atomicity, versioning."""

import struct

import pytest
from django.test import RequestFactory

from dbs.container.format import HEADER_SIZE
from dbs.crypto.kdf import KDFParams
from dbs.engine import create_backup, restore_backup, validate_backup
from dbs.exceptions import ContainerError, CorruptionError, CryptoError, RestoreError
from dbs.files import FileEntry, _sha256, restore_file
from dbs.serialize import load_records
from tests.conftest import FAST_KDF
from tests.testapp.models import Author, Book

PASS = "hardening-pass-phrase"


def test_restore_refuses_path_outside_restore_roots(tmp_path, settings):
    settings.DBS_RESTORE_ROOTS = [str(tmp_path / "allowed")]
    data = b"payload"
    entry = FileEntry(
        kind="path", size=len(data), sha256=_sha256(data),
        name=str(tmp_path / "outside.bin"),
    )
    with pytest.raises(RestoreError):
        restore_file(entry, data)


def test_restore_refuses_parent_traversal(tmp_path, settings):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    settings.DBS_RESTORE_ROOTS = [str(allowed)]
    data = b"payload"
    entry = FileEntry(
        kind="root", size=len(data), sha256=_sha256(data),
        root=str(allowed), name="../escape.bin",
    )
    with pytest.raises(RestoreError):
        restore_file(entry, data)
    assert not (tmp_path / "escape.bin").exists()


def test_restore_refuses_everything_when_no_roots_configured(tmp_path):
    data = b"payload"
    entry = FileEntry(
        kind="path", size=len(data), sha256=_sha256(data),
        name=str(tmp_path / "file.bin"),
    )
    with pytest.raises(RestoreError):
        restore_file(entry, data)


def test_restore_writes_inside_allowed_root(tmp_path, settings):
    settings.DBS_RESTORE_ROOTS = [str(tmp_path)]
    data = b"payload"
    target = tmp_path / "sub" / "file.bin"
    entry = FileEntry(
        kind="path", size=len(data), sha256=_sha256(data), name=str(target)
    )
    restore_file(entry, data)
    assert target.read_bytes() == data


def test_kdf_params_reject_excessive_memory():
    with pytest.raises(CryptoError):
        KDFParams.from_dict(
            {"time_cost": 3, "memory_cost": 64 * 1024 * 1024, "parallelism": 4}
        )


def test_kdf_params_reject_zero_time_cost():
    with pytest.raises(CryptoError):
        KDFParams.from_dict({"time_cost": 0, "memory_cost": 8, "parallelism": 1})


@pytest.mark.django_db
def test_failed_restore_rolls_back_all_rows():
    records = [
        {"model": "testapp.author", "pk": 1, "fields": {"name": "Ada"}},
        {
            "model": "testapp.book",
            "pk": 1,
            "fields": {
                "title": "Orphan",
                "author": 999,
                "tags": [],
                "cover": "",
                "sidecar_path": "",
            },
        },
    ]
    with pytest.raises(Exception):
        load_records(records)
    assert not Author.objects.exists()
    assert not Book.objects.exists()


@pytest.mark.django_db
def test_backup_output_is_written_atomically(tmp_path):
    Author.objects.create(name="Ada")
    out = tmp_path / "backup.dbs"
    container = create_backup(PASS, kdf_params=FAST_KDF, output=str(out))
    assert out.read_bytes() == container
    assert not (tmp_path / "backup.dbs.tmp").exists()


@pytest.mark.django_db
def test_unknown_format_version_is_rejected():
    Author.objects.create(name="Ada")
    container = bytearray(create_backup(PASS, kdf_params=FAST_KDF))
    struct.pack_into(">H", container, 8, 99)
    struct.pack_into(">H", container, len(container) - HEADER_SIZE + 8, 99)
    with pytest.raises(ContainerError):
        restore_backup(bytes(container), PASS)


@pytest.mark.django_db
def test_version_check_falls_back_to_trailer_header():
    Author.objects.create(name="Ada")
    container = bytearray(create_backup(PASS, kdf_params=FAST_KDF))
    struct.pack_into(">H", container, 8, 99)
    result = validate_backup(bytes(container), PASS)
    assert result.ok and result.decrypted_ok


@pytest.mark.django_db
def test_missing_source_file_is_reported(tmp_path):
    author = Author.objects.create(name="Ada")
    Book.objects.create(
        title="Ghost", author=author, sidecar_path=str(tmp_path / "gone.dat")
    )
    container = create_backup(PASS, kdf_params=FAST_KDF)
    result = validate_backup(container, PASS)
    assert any("gone.dat" in item for item in result.stats["skipped_files"])


@pytest.mark.django_db
def test_payload_size_limit_is_enforced(settings):
    Author.objects.create(name="Ada")
    container = create_backup(PASS, kdf_params=FAST_KDF)
    settings.DBS_MAX_PAYLOAD_BYTES = 8
    with pytest.raises(CorruptionError):
        restore_backup(container, PASS)


def test_admin_render_escapes_messages():
    from dbs.contrib.admin import _render

    request = RequestFactory().get("/dbs/restore/")
    response = _render(
        request, "Restore", "", message='{{ 7|add:"7" }}<script>alert(1)</script>'
    )
    assert b"&lt;script&gt;" in response.content
    assert b"<script>alert" not in response.content
    assert b"{{ 7|add:" in response.content
