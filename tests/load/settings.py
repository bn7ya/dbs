import os
import tempfile

import django
from django.db.backends.signals import connection_created

from tests.settings import *  # noqa: F401,F403
from tests.settings import DATABASES, INSTALLED_APPS

FOLDER = os.environ.setdefault(
    "DBS_LOAD_FOLDER", tempfile.mkdtemp(prefix="dbs-load-")
)
IMMEDIATE = {"transaction_mode": "IMMEDIATE"} if django.VERSION >= (5, 1) else {}
INSTALLED_APPS = [*INSTALLED_APPS, "tests.load.loadapp"]
MIGRATION_MODULES = {"loadapp": None}
ROOT_URLCONF = "tests.load.loadapp.urls"
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]
DEBUG = False
DBS_JOB_PROCESS = True
DBS_BACKUP_DIR = os.path.join(FOLDER, "backups")

if DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.path.join(FOLDER, "load.sqlite3"),
            "TEST": {"NAME": os.path.join(FOLDER, "load.sqlite3")},
            "OPTIONS": {"timeout": 30, **IMMEDIATE},
        }
    }
DATABASES["restored"] = {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": os.path.join(FOLDER, "restored.sqlite3"),
    "TEST": {"NAME": os.path.join(FOLDER, "restored.sqlite3")},
}


def write_ahead(sender, connection, **kwargs):
    if connection.vendor == "sqlite":
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA journal_mode=WAL")


connection_created.connect(write_ahead)
