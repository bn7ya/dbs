import threading

import pytest
from django.db import connection, connections, transaction

from dbs.engine import backup as backup_module
from dbs.engine import create_backup, restore_backup
from tests.payloads import read_payload
from dbs.registry import BackupRegistry
from tests.conftest import FAST_KDF
from tests.testapp.models import Author, Book

PASS = "snapshot-pass-phrase"

postgres_only = pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="Snapshot isolation is backend specific; run with DBS_TEST_DB=postgres.",
)


def _registry():
    registry = BackupRegistry()
    registry.register(Author)
    registry.register(Book)
    return registry


def _commit_a_new_author_and_book():
    try:
        grace = Author.objects.create(name="Grace")
        Book.objects.create(title="Written mid-backup", author=grace)
    finally:
        connections.close_all()


def _write_after_serializing(model_to_watch, monkeypatch):
    real = backup_module.serialize_batches

    def serialize_then_write(model, *args, **kwargs):
        yield from real(model, *args, **kwargs)
        if model is model_to_watch:
            writer = threading.Thread(target=_commit_a_new_author_and_book)
            writer.start()
            writer.join()

    monkeypatch.setattr(backup_module, "serialize_batches", serialize_then_write)


@postgres_only
@pytest.mark.django_db(transaction=True)
def test_rows_committed_during_a_backup_never_split_it(monkeypatch):
    ada = Author.objects.create(name="Ada")
    Book.objects.create(title="Notes", author=ada)
    _write_after_serializing(Author, monkeypatch)

    container = create_backup(PASS, registry=_registry(), kdf_params=FAST_KDF)

    records = read_payload(container, PASS).records
    authors = {record["pk"] for record in records if record["model"] == "testapp.author"}
    books = [record for record in records if record["model"] == "testapp.book"]
    assert authors == {ada.pk}
    assert [book["fields"]["title"] for book in books] == ["Notes"]

    Book.objects.all().delete()
    Author.objects.all().delete()
    restore_backup(container, PASS)
    assert Book.objects.get().author_id == ada.pk


@postgres_only
@pytest.mark.django_db(transaction=True)
def test_a_backup_inside_a_callers_transaction_still_completes():
    Author.objects.create(name="Ada")

    with transaction.atomic():
        Author.objects.create(name="Grace")
        container = create_backup(PASS, registry=_registry(), kdf_params=FAST_KDF)

    names = sorted(
        record["fields"]["name"]
        for record in read_payload(container, PASS).records
        if record["model"] == "testapp.author"
    )
    assert names == ["Ada", "Grace"]

