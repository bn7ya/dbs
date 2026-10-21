import sqlite3
from contextlib import closing

import pytest
from django.db import connection

from dbs.engine import backup as backup_module
from dbs.engine import create_backup
from dbs.registry import BackupRegistry
from tests.conftest import FAST_KDF
from tests.payloads import read_payload
from tests.testapp.models import Author, Book

PASS = "sqlite-snapshot-pass-phrase"

pytestmark = [
    pytest.mark.skipif(connection.vendor != "sqlite", reason="Runs on a SQLite database file."),
    pytest.mark.django_db(transaction=True),
]


@pytest.fixture
def write_ahead_log():
    database = connection.settings_dict["NAME"]
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA journal_mode=WAL")
    yield database
    connection.close()
    with closing(sqlite3.connect(database)) as raw:
        raw.execute("PRAGMA journal_mode=DELETE")


def test_the_site_keeps_writing_while_a_backup_reads_one_snapshot(write_ahead_log, monkeypatch):
    ada = Author.objects.create(name="Ada")
    Book.objects.create(title="Notes", author=ada)
    real = backup_module.serialize_batches

    def serialize_then_write(model, *args, **kwargs):
        yield from real(model, *args, **kwargs)
        if model is Author:
            with closing(sqlite3.connect(write_ahead_log, timeout=0)) as site:
                grace = site.execute("INSERT INTO testapp_author (name) VALUES ('Grace')")
                site.execute(
                    "INSERT INTO testapp_book (title, author_id, cover, sidecar_path) "
                    "VALUES ('Written mid-backup', ?, '', '')",
                    (grace.lastrowid,),
                )
                site.commit()

    monkeypatch.setattr(backup_module, "serialize_batches", serialize_then_write)
    registry = BackupRegistry()
    registry.register(Author)
    registry.register(Book)

    container = create_backup(PASS, registry=registry, kdf_params=FAST_KDF)

    records = read_payload(container, PASS).records
    authors = [record["pk"] for record in records if record["model"] == "testapp.author"]
    books = [record["fields"]["title"] for record in records if record["model"] == "testapp.book"]
    assert (authors, books) == ([ada.pk], ["Notes"])
    assert Book.objects.count() == 2
