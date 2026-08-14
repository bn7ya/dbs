"""Restoring explicit primary keys must leave usable sequences behind."""

import pytest
from django.db import connection

from dbs.engine import create_backup, restore_backup
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


def _restart_sequence(model):
    sequence = _sequence_name(model)
    with connection.cursor() as cursor:
        cursor.execute(f"ALTER SEQUENCE {sequence} RESTART WITH 1")


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
