from io import StringIO

import pytest
from django.core.files.base import ContentFile
from django.core.management import call_command

from dbs.engine import create_backup, restore_backup
from tests.payloads import read_payload
from dbs.registry import BackupRegistry
from tests.conftest import FAST_KDF
from tests.testapp.dbs import BookBackup
from tests.testapp.models import Author, Book

PASS = "using-pass-phrase"

BOTH = pytest.mark.django_db(databases=["default", "secondary"])


def _books():
    registry = BackupRegistry()
    registry.register(Author)
    registry.register(Book)(BookBackup)
    return registry


def _names(container, label):
    return sorted(
        record["fields"].get("name") or record["fields"].get("title")
        for record in read_payload(container, PASS).records
        if record["model"] == label
    )


@BOTH
def test_rows_are_read_from_the_database_the_backup_names():
    Author.objects.using("default").create(name="Default Ada")
    Author.objects.using("secondary").create(name="Secondary Grace")

    container = create_backup(PASS, registry=_books(), using="secondary", kdf_params=FAST_KDF)

    assert _names(container, "testapp.author") == ["Secondary Grace"]


@BOTH
def test_files_are_collected_from_the_rows_of_that_database(tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path / "media")
    sidecar = tmp_path / "sidecar.dat"
    sidecar.write_bytes(b"SIDECAR")
    author = Author.objects.using("secondary").create(name="Grace")
    book = Book(title="Secondary", author=author, sidecar_path=str(sidecar))
    book.cover.save("cover.bin", ContentFile(b"COVER"), save=False)
    book.save(using="secondary")

    container = create_backup(PASS, registry=_books(), using="secondary", kdf_params=FAST_KDF)

    payload = read_payload(container, PASS)
    assert sorted(data for _entry, data in payload.files) == [b"COVER", b"SIDECAR"]
    assert _names(container, "testapp.book") == ["Secondary"]


@BOTH
def test_the_database_option_reaches_the_rows(tmp_path):
    Author.objects.using("default").create(name="Default Ada")
    Author.objects.using("secondary").create(name="Secondary Grace")
    output = tmp_path / "secondary.dbs"

    call_command(
        "dbs", "backup", str(output),
        passphrase=PASS, database="secondary", kdf_time=1, kdf_memory=8192, stdout=StringIO(),
    )

    restored = restore_backup(output.read_bytes(), PASS, dry_run=True, using="secondary")
    assert restored.records_would_load >= 1
    names = [
        record["fields"]["name"]
        for record in read_payload(output.read_bytes(), PASS).records
        if record["model"] == "testapp.author"
    ]
    assert names == ["Secondary Grace"]
