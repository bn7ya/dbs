"""Throwaway Django projects that the checkpoint tests drive through manage.py."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from django.db.utils import ConnectionHandler

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parent.parent
STAGES = HERE / "stages"
SEQUENCE = ("1", "2", "3", "4", "5")
VENDOR = os.environ.get("DBS_TEST_DB", "sqlite")
QUERY = (
    "import json, sys; import django; django.setup(); "
    "from django.db import connection; cursor = connection.cursor(); "
    "cursor.execute(sys.argv[1]); print(json.dumps([list(row) for row in cursor.fetchall()], default=str))"
)
COLUMNS = (
    "import json, sys; import django; django.setup(); "
    "from django.db import connection; cursor = connection.cursor(); "
    "found = connection.introspection.table_names(cursor); "
    "print(json.dumps({name: [column.name for column in "
    "connection.introspection.get_table_description(cursor, name)] for name in found}))"
)


@dataclass
class Ran:
    code: int
    out: str
    err: str

    @property
    def text(self) -> str:
        return self.out + self.err


def server(vendor: str) -> dict:
    if vendor == "postgres":
        return {
            "ENGINE": "django.db.backends.postgresql",
            "USER": os.environ.get("DBS_TEST_PG_USER", "postgres"),
            "PASSWORD": os.environ.get("DBS_TEST_PG_PASSWORD", ""),
            "HOST": os.environ.get("DBS_TEST_PG_HOST", "localhost"),
            "PORT": os.environ.get("DBS_TEST_PG_PORT", "5432"),
        }
    return {
        "ENGINE": "django.db.backends.mysql",
        "USER": os.environ.get("DBS_TEST_MYSQL_USER", "root"),
        "PASSWORD": os.environ.get("DBS_TEST_MYSQL_PASSWORD", ""),
        "HOST": os.environ.get("DBS_TEST_MYSQL_HOST", "127.0.0.1"),
        "PORT": os.environ.get("DBS_TEST_MYSQL_PORT", "3306"),
        "OPTIONS": {"charset": "utf8mb4"},
    }


def administer(statement: str) -> None:
    maintenance = "postgres" if VENDOR == "postgres" else ""
    handler = ConnectionHandler({"default": {**server(VENDOR), "NAME": maintenance}})
    connection = handler["default"]
    try:
        connection.ensure_connection()
        connection.set_autocommit(True)
        with connection.cursor() as cursor:
            cursor.execute(statement)
    finally:
        connection.close()


class Database:
    def __init__(self, folder: Path):
        self.name = f"dbs_cp_{uuid.uuid4().hex[:12]}"
        if VENDOR == "sqlite":
            self.settings = {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": str(folder / f"{self.name}.sqlite3"),
            }
            return
        administer(f"CREATE DATABASE {self.name}")
        self.settings = {**server(VENDOR), "NAME": self.name}

    def drop(self) -> None:
        if VENDOR != "sqlite":
            administer(f"DROP DATABASE IF EXISTS {self.name}")


class Project:
    def __init__(self, root: Path, source: str, package: str, database: Database, backups=None):
        self.root = root
        self.package = package
        self.database = database
        self.backups = backups
        self.options: dict = {}
        shutil.copytree(HERE / source, root)

    def at(self, stage: str) -> "Project":
        app = self.root / "ledger"
        shutil.copy(STAGES / stage / "models.py", app / "models.py")
        for path in (app / "migrations").glob("0*.py"):
            path.unlink()
        included = SEQUENCE[: SEQUENCE.index(stage) + 1] if stage in SEQUENCE else (*SEQUENCE[:4], stage)
        for name in included:
            for migration in (STAGES / name / "migrations").glob("0*.py"):
                shutil.copy(migration, app / "migrations" / migration.name)
        shutil.rmtree(app / "__pycache__", ignore_errors=True)
        shutil.rmtree(app / "migrations" / "__pycache__", ignore_errors=True)
        return self

    def environment(self, **extra) -> dict:
        env = {
            **os.environ,
            "DJANGO_SETTINGS_MODULE": f"{self.package}.settings",
            "PROJECT_DATABASE": json.dumps(self.database.settings),
            "PROJECT_BACKUP_DIR": str(self.backups) if self.backups else "",
            "PYTHONPATH": os.pathsep.join([str(self.root), str(REPOSITORY)]),
            "PYTHONDONTWRITEBYTECODE": "1",
            **{key: str(value) for key, value in self.options.items()},
            **{key: str(value) for key, value in extra.items()},
        }
        env.pop("DBS_PASSPHRASE", None)
        return env

    def python(self, *arguments, check: bool = True, **extra) -> Ran:
        done = subprocess.run(
            [sys.executable, *arguments],
            cwd=self.root,
            env=self.environment(**extra),
            capture_output=True,
            text=True,
            timeout=300,
        )
        ran = Ran(done.returncode, done.stdout, done.stderr)
        if check and ran.code != 0:
            raise AssertionError(f"{arguments} exited {ran.code}:\n{ran.text}")
        return ran

    def manage(self, *arguments, check: bool = True, **extra) -> Ran:
        return self.python("manage.py", *arguments, check=check, **extra)

    def run(self, code: str) -> str:
        return self.python("-c", f"import django; django.setup()\n{code}").out

    def query(self, statement: str) -> list:
        return json.loads(self.python("-c", QUERY, statement).out)

    def tables(self) -> dict:
        return json.loads(self.python("-c", COLUMNS).out)

    def columns(self, table: str) -> list:
        return self.tables()[table]

    def applied(self, app: str = "ledger") -> list:
        rows = self.query("SELECT app, name FROM django_migrations ORDER BY id")
        return [name for found, name in rows if found == app]

    def checkpoints(self) -> list:
        if not self.backups or not self.backups.is_dir():
            return []
        return sorted(path.name for path in self.backups.glob("*.dbs"))

    def listed(self) -> list:
        return json.loads(self.manage("dbs", "checkpoints", "--json").out)

    def roles(self) -> list:
        return [entry["role"] for entry in self.listed()]

    def checkpoint(self, role: str, migration: str = "") -> Path:
        found = [
            entry
            for entry in self.listed()
            if entry["role"] == role and (not migration or migration in (entry["migrations"] or []))
        ]
        return Path(found[-1]["path"])

    def migrate_to(self, *stages: str) -> Ran:
        ran = None
        for stage in stages:
            ran = self.at(stage).manage("migrate", "--noinput")
        return ran
