"""Restoring explicit primary keys must leave usable sequences behind."""

import pytest
from django.db import connection

from dbs import serialize
from dbs.engine import create_backup, restore_backup
from dbs.registry import BackupRegistry
from tests.conftest import FAST_KDF
from tests.testapp.models import Author

PASS = "test-pass-phrase"

postgres_only = pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="Sequence resets are backend specific; run with DBS_TEST_DB=postgres.",
)


def _sequence_name(model):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_get_serial_sequence(%s, %s)",
            [model._meta.db_table, model._meta.pk.column],
        )
        return cursor.fetchone()[0]


def _restart_sequence(model, value=1):
    sequence = _sequence_name(model)
    with connection.cursor() as cursor:
        cursor.execute(f"ALTER SEQUENCE {sequence} RESTART WITH {int(value)}")


def _authors():
    registry = BackupRegistry()
    registry.register(Author)
    return registry


def _three_authors_backed_up():
    for name in ("Ada", "Grace", "Alan"):
        Author.objects.create(name=name)
    return create_backup(PASS, registry=_authors(), kdf_params=FAST_KDF)


def _next_sequence_value(model):
    sequence = _sequence_name(model)
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT last_value, is_called FROM {sequence}")
        last_value, is_called = cursor.fetchone()
    return last_value + 1 if is_called else last_value


@postgres_only
@pytest.mark.django_db(transaction=True)
def test_restore_into_fresh_database_leaves_insertable_sequences():
    for name in ("Ada", "Grace", "Alan"):
        Author.objects.create(name=name)
    container = create_backup(PASS, kdf_params=FAST_KDF)
    highest = Author.objects.order_by("-pk").first().pk

    Author.objects.all().delete()
    _restart_sequence(Author)

    restore_backup(container, PASS)

    assert Author.objects.count() == 3
    assert _next_sequence_value(Author) > highest

    created = Author.objects.create(name="Katherine")
    assert created.pk > highest


@postgres_only
@pytest.mark.django_db(transaction=True)
def test_restore_without_rows_leaves_sequences_untouched():
    Author.objects.all().delete()
    _restart_sequence(Author)

    container = create_backup(PASS, kdf_params=FAST_KDF)
    restore_backup(container, PASS)

    assert _next_sequence_value(Author) == 1


@pytest.mark.django_db
def test_only_a_real_restore_adjusts_sequences(monkeypatch):
    container = _three_authors_backed_up()
    Author.objects.all().delete()
    adjusted = []
    real = serialize.raise_sequences
    monkeypatch.setattr(
        serialize,
        "raise_sequences",
        lambda connection, models: adjusted.append(set(models)) or real(connection, models),
    )

    out = restore_backup(container, PASS, dry_run=True, registry=_authors())

    assert out.records_would_load == 3
    assert adjusted == []

    restore_backup(container, PASS, registry=_authors())

    assert adjusted == [{Author}]


@postgres_only
@pytest.mark.django_db(transaction=True)
def test_a_dry_run_leaves_sequences_where_they_were():
    container = _three_authors_backed_up()
    Author.objects.all().delete()
    _restart_sequence(Author)

    restore_backup(container, PASS, dry_run=True, registry=_authors())

    assert _next_sequence_value(Author) == 1


@postgres_only
@pytest.mark.django_db(transaction=True)
def test_a_restore_never_lowers_a_sequence():
    container = _three_authors_backed_up()
    _restart_sequence(Author, 500)

    restore_backup(container, PASS, flush=True, registry=_authors())

    assert Author.objects.count() == 3
    assert _next_sequence_value(Author) == 500


@postgres_only
@pytest.mark.django_db(transaction=True)
def test_a_restore_raises_a_sequence_that_lags_behind_the_rows():
    container = _three_authors_backed_up()
    highest = Author.objects.order_by("-pk").first().pk
    _restart_sequence(Author, 2)

    restore_backup(container, PASS, registry=_authors())

    assert _next_sequence_value(Author) == highest + 1
