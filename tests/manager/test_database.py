import sqlite3
import threading
import time

import django
import pytest
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.db import DEFAULT_DB_ALIAS, connections, transaction
from django.db.utils import ConnectionHandler

from dbs import transactions
from dbs.manager.apps import SQLITE_PRAGMAS, tune_sqlite
from dbs.manager.database import (
    SQLITE_ENGINE,
    DatabaseURLError,
    parse_database_url,
    sqlite_database,
)

BACKPORT = "dbs.manager.sqlite"


def opened(settings):
    return ConnectionHandler({"default": settings})["default"]


@pytest.fixture
def manager_database(tmp_path, transactional_db):
    usual = connections[DEFAULT_DB_ALIAS]
    database = opened(sqlite_database(tmp_path / "manager.sqlite3"))
    connections[DEFAULT_DB_ALIAS] = database
    yield database
    connections[DEFAULT_DB_ALIAS] = usual
    database.close()


def the_write_lock_is_free(database):
    other = sqlite3.connect(database.settings_dict["NAME"], timeout=0.2, isolation_level=None)
    try:
        other.execute("BEGIN IMMEDIATE")
        other.execute("ROLLBACK")
    except sqlite3.OperationalError:
        return False
    finally:
        other.close()
    return True


def another_write(database, seconds):
    holding = threading.Event()

    def write():
        other = sqlite3.connect(database.settings_dict["NAME"], timeout=5, isolation_level=None)
        other.execute("BEGIN IMMEDIATE")
        holding.set()
        time.sleep(seconds)
        other.execute("COMMIT")
        other.close()

    thread = threading.Thread(target=write)
    thread.start()
    holding.wait()
    return thread


def first_statement_of_a_transaction(database):
    statements = []

    def noted(execute, sql, params, many, context):
        statements.append(sql)
        return execute(sql, params, many, context)

    database.ensure_connection()
    with database.execute_wrapper(noted):
        database.set_autocommit(False, force_begin_transaction_with_broken_autocommit=True)
        database.rollback()
        database.set_autocommit(True)
    return statements[0]


def test_the_default_database_is_sqlite_with_a_generous_timeout(tmp_path):
    database = sqlite_database(tmp_path / "manager.sqlite3")

    assert database["ENGINE"] == SQLITE_ENGINE
    assert database["NAME"] == str(tmp_path / "manager.sqlite3")
    assert database["OPTIONS"]["timeout"] == 30


def test_sqlite_transactions_take_the_write_lock_when_they_begin(tmp_path):
    database = sqlite_database(tmp_path / "manager.sqlite3")

    assert database["OPTIONS"]["transaction_mode"] == "IMMEDIATE"


def test_django_before_5_1_gets_the_backend_that_knows_transaction_mode():
    stock = "django.db.backends.sqlite3"

    assert SQLITE_ENGINE == (stock if django.VERSION >= (5, 1) else BACKPORT)


def test_a_write_holds_the_write_lock_from_its_first_moment(manager_database):
    with transaction.atomic():
        assert not the_write_lock_is_free(manager_database)

    assert the_write_lock_is_free(manager_database)


def test_a_read_begins_without_the_write_lock(manager_database):
    with transactions.reading():
        with manager_database.cursor() as cursor:
            cursor.execute("SELECT 1")
        assert the_write_lock_is_free(manager_database)


def test_a_cache_write_waits_for_another_write_instead_of_being_lost(
    manager_database, settings
):
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.db.DatabaseCache",
            "LOCATION": "probe_cache",
        }
    }
    call_command("createcachetable", verbosity=0)
    writing = another_write(manager_database, seconds=0.5)

    cache.set("health:probe", "1", timeout=5)
    kept = cache.get("health:probe")
    writing.join()

    assert kept == "1"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("options", "begins"),
    [
        ({}, "BEGIN"),
        ({"transaction_mode": "DEFERRED"}, "BEGIN DEFERRED"),
        ({"transaction_mode": "IMMEDIATE"}, "BEGIN IMMEDIATE"),
        ({"transaction_mode": "EXCLUSIVE"}, "BEGIN EXCLUSIVE"),
    ],
)
def test_the_backport_begins_a_transaction_as_transaction_mode_says(tmp_path, options, begins):
    database = opened(
        {"ENGINE": BACKPORT, "NAME": str(tmp_path / "manager.sqlite3"), "OPTIONS": options}
    )

    try:
        assert first_statement_of_a_transaction(database) == begins
    finally:
        database.close()


@pytest.mark.django_db
def test_the_backport_refuses_a_transaction_mode_sqlite_does_not_have(tmp_path):
    database = opened(
        {
            "ENGINE": BACKPORT,
            "NAME": str(tmp_path / "manager.sqlite3"),
            "OPTIONS": {"transaction_mode": "SOON"},
        }
    )

    with pytest.raises(ImproperlyConfigured, match="transaction_mode"):
        database.ensure_connection()


@pytest.mark.parametrize(
    ("url", "name"),
    [
        ("sqlite:////var/lib/dbs/manager.sqlite3", "/var/lib/dbs/manager.sqlite3"),
        ("sqlite:///relative.sqlite3", "relative.sqlite3"),
        ("sqlite://:memory:", ":memory:"),
        ("sqlite://", ":memory:"),
    ],
)
def test_sqlite_urls(url, name):
    database = parse_database_url(url)

    assert database["ENGINE"] == SQLITE_ENGINE
    assert database["NAME"] == name
    assert database["OPTIONS"]["timeout"] == 30


def test_a_postgres_url_names_every_part():
    database = parse_database_url(
        "postgres://dbs:s%40cret@db.internal:6543/manager?sslmode=require"
    )

    assert database == {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "manager",
        "USER": "dbs",
        "PASSWORD": "s@cret",
        "HOST": "db.internal",
        "PORT": "6543",
        "OPTIONS": {"sslmode": "require"},
    }


def test_a_mysql_url_takes_the_default_port():
    database = parse_database_url("mysql://root@localhost/manager")

    assert database["ENGINE"] == "django.db.backends.mysql"
    assert (database["HOST"], database["PORT"], database["PASSWORD"]) == (
        "localhost",
        "3306",
        "",
    )


@pytest.mark.parametrize("url", ["redis://localhost/0", "postgres://host/", "nonsense"])
def test_a_url_the_manager_cannot_use_is_refused(url):
    with pytest.raises(DatabaseURLError):
        parse_database_url(url)


class FakeCursor:
    def __init__(self, executed):
        self.executed = executed

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, statement):
        self.executed.append(statement)


class FakeConnection:
    def __init__(self, vendor):
        self.vendor = vendor
        self.executed = []

    def cursor(self):
        return FakeCursor(self.executed)


def test_every_sqlite_connection_gets_wal_a_busy_timeout_and_foreign_keys():
    connection = FakeConnection("sqlite")

    tune_sqlite(sender=None, connection=connection)

    assert connection.executed == list(SQLITE_PRAGMAS)
    assert "PRAGMA journal_mode=WAL" in connection.executed
    assert "PRAGMA busy_timeout=30000" in connection.executed
    assert "PRAGMA foreign_keys=ON" in connection.executed


def test_other_databases_are_left_alone():
    connection = FakeConnection("postgresql")

    tune_sqlite(sender=None, connection=connection)

    assert connection.executed == []
