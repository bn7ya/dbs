import pytest

from dbs.manager.apps import SQLITE_PRAGMAS, tune_sqlite
from dbs.manager.database import DatabaseURLError, parse_database_url, sqlite_database


def test_the_default_database_is_sqlite_with_a_generous_timeout(tmp_path):
    database = sqlite_database(tmp_path / "manager.sqlite3")

    assert database == {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(tmp_path / "manager.sqlite3"),
        "OPTIONS": {"timeout": 30},
    }


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

    assert database["ENGINE"] == "django.db.backends.sqlite3"
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
