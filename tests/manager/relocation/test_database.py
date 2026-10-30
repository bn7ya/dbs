from __future__ import annotations

import json

import pytest

from dbs.manager.relocation import database
from dbs.manager.relocation.database import Credentials


def test_postgresql_statements_escape_the_password_and_quote_names():
    sql = database.postgres_statements(
        Credentials("postgresql", "shop", "shop_user", "it's a \\ secret"),
        create_role=True,
    ).decode()

    assert sql == (
        "CREATE ROLE \"shop_user\" LOGIN PASSWORD 'it''s a \\ secret';\n"
        "CREATE DATABASE \"shop\" OWNER \"shop_user\" ENCODING 'UTF8';\n"
    )


def test_an_existing_role_keeps_its_password():
    sql = database.postgres_statements(
        Credentials("postgresql", "shop", "shop", "pw"), create_role=False
    ).decode()

    assert "ROLE" not in sql and "pw" not in sql


def test_mysql_statements_escape_backslashes_and_quotes():
    sql = database.mysql_statements(
        Credentials("mysql", "shop", "shop", "a'b\\c"), hosts=("localhost",)
    ).decode()

    assert "IDENTIFIED BY 'a''b\\\\c';" in sql
    assert sql.startswith("CREATE DATABASE `shop` CHARACTER SET utf8mb4")
    assert "GRANT ALL PRIVILEGES ON `shop`.* TO 'shop'@'localhost';" in sql


@pytest.mark.parametrize("name", ["shop-db", "a\"b", "x; DROP", "", "1shop", "a" * 64])
def test_names_a_move_cannot_create_safely_are_refused(name):
    with pytest.raises(ValueError):
        database.postgres_statements(Credentials("postgresql", name, "shop", "pw"), create_role=True)
    with pytest.raises(ValueError):
        database.mysql_exists(name)


def test_a_password_with_a_nul_is_refused():
    with pytest.raises(ValueError):
        database.mysql_literal("a\0b")


def test_the_credentials_are_read_from_the_marked_line_only():
    stdout = "noise\n" + database.SECRET_MARKER + json.dumps(
        {"vendor": "postgresql", "name": "shop", "user": "shop", "password": "pw"}
    )

    found = database.credentials_of(stdout)

    assert found == Credentials("postgresql", "shop", "shop", "pw")
    assert "pw" not in repr(found)
    assert database.credentials_of("no marker") is None
    assert database.credentials_of(database.SECRET_MARKER + '{"name": 1}') is None
