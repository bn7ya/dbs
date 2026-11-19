import sqlite3

import django
import pytest
from django.db import connection

from dbs import transactions
from dbs.engine.backup import one_snapshot
from tests.testapp.models import Author

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(connection.vendor != "sqlite", reason="SQLite has one write lock"),
]


@pytest.fixture(autouse=True)
def write_ahead_log(transactional_db):
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA journal_mode=WAL")
    yield
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA user_version = 0")
        cursor.execute("PRAGMA journal_mode=DELETE")


def the_site_can_write():
    site = sqlite3.connect(connection.settings_dict["NAME"], timeout=0.2, isolation_level=None)
    try:
        site.execute("BEGIN IMMEDIATE")
        site.execute("PRAGMA user_version = 1")
        site.execute("COMMIT")
    except sqlite3.OperationalError:
        return False
    finally:
        site.close()
    return True


def test_a_read_leaves_the_write_lock_to_the_site():
    with transactions.reading():
        assert Author.objects.count() == 0
        assert the_site_can_write()


def test_a_backup_reads_from_one_snapshot_while_the_site_writes():
    with one_snapshot("default"):
        assert Author.objects.count() == 0
        writer = sqlite3.connect(connection.settings_dict["NAME"], timeout=0.2)
        with writer:
            writer.execute("INSERT INTO testapp_author (name) VALUES ('written meanwhile')")
        writer.close()
        assert Author.objects.count() == 0

    assert Author.objects.count() == 1


@pytest.mark.skipif(django.VERSION < (5, 1), reason="Django 5.1 added transaction_mode")
def test_a_write_still_takes_the_write_lock_as_it_begins():
    with transactions.atomic():
        assert Author.objects.count() == 0
        assert not the_site_can_write()

    assert connection.transaction_mode == "IMMEDIATE"


def test_a_read_inside_a_write_stays_in_it():
    with transactions.atomic():
        Author.objects.create(name="kept")
        with transactions.reading():
            assert Author.objects.count() == 1

    assert Author.objects.count() == 1
