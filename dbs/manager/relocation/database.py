from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

DB_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
SECRET_MARKER = "DBS-DATABASE "
POSTGRESQL = "postgresql"
MYSQL = "mysql"
MYSQL_HOSTS = ("localhost", "127.0.0.1", "::1")
DATABASE_SECRET = """
import json
from django.conf import settings
from django.db import connections
default = settings.DATABASES.get("default") or {}
print("DBS-DATABASE " + json.dumps({
    "vendor": connections["default"].vendor if default else "",
    "name": str(default.get("NAME") or ""),
    "user": str(default.get("USER") or ""),
    "password": str(default.get("PASSWORD") or ""),
}))
"""


@dataclass(frozen=True)
class Credentials:
    vendor: str
    name: str
    user: str
    password: str = field(repr=False)


def identifier(value: str) -> str:
    if not isinstance(value, str) or not DB_IDENT.match(value):
        raise ValueError(f"Not a database name this move can create: {value!r}")
    return value


def credentials_of(stdout: str) -> Credentials | None:
    line = next(
        (
            line[len(SECRET_MARKER) :]
            for line in reversed(stdout.splitlines())
            if line.startswith(SECRET_MARKER)
        ),
        None,
    )
    if line is None:
        return None
    try:
        found = json.loads(line)
    except ValueError:
        return None
    if not isinstance(found, dict):
        return None
    values = [found.get(key) for key in ("vendor", "name", "user", "password")]
    if not all(isinstance(value, str) for value in values):
        return None
    return Credentials(*values)


def postgres_literal(value: str) -> str:
    if "\0" in value:
        raise ValueError("A password cannot hold a NUL character.")
    return "'" + value.replace("'", "''") + "'"


def mysql_literal(value: str) -> str:
    if "\0" in value:
        raise ValueError("A password cannot hold a NUL character.")
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def postgres_exists(name: str) -> str:
    return f"SELECT 1 FROM pg_database WHERE datname = '{identifier(name)}'"


def postgres_role_exists(user: str) -> str:
    return f"SELECT 1 FROM pg_roles WHERE rolname = '{identifier(user)}'"


def postgres_statements(credentials: Credentials, *, create_role: bool) -> bytes:
    name = identifier(credentials.name)
    user = identifier(credentials.user)
    lines = []
    if create_role:
        lines.append(
            f'CREATE ROLE "{user}" LOGIN PASSWORD {postgres_literal(credentials.password)};'
        )
    lines.append(f'CREATE DATABASE "{name}" OWNER "{user}" ENCODING \'UTF8\';')
    return ("\n".join(lines) + "\n").encode()


def mysql_exists(name: str) -> str:
    return (
        "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA "
        f"WHERE SCHEMA_NAME = '{identifier(name)}'"
    )


def mysql_statements(credentials: Credentials, hosts: Iterable[str] = MYSQL_HOSTS) -> bytes:
    name = identifier(credentials.name)
    user = identifier(credentials.user)
    secret = mysql_literal(credentials.password)
    lines = [f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"]
    for host in hosts:
        if host not in MYSQL_HOSTS:
            raise ValueError(f"Not a host this move grants: {host!r}")
        lines.append(f"CREATE USER IF NOT EXISTS '{user}'@'{host}' IDENTIFIED BY {secret};")
        lines.append(f"GRANT ALL PRIVILEGES ON `{name}`.* TO '{user}'@'{host}';")
    lines.append("FLUSH PRIVILEGES;")
    return ("\n".join(lines) + "\n").encode()


def vendor_need(vendor: str, flavour: str = "") -> str:
    if vendor == POSTGRESQL:
        return "postgresql"
    if vendor == MYSQL:
        return "mariadb" if flavour == "mariadb" else "mysql"
    return ""
