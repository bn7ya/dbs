import os
import tempfile

from dbs.manager.database import sqlite_database
from tests.manager.settings import *  # noqa: F401,F403
from tests.manager.settings import TEST_DATABASE_URL

if not TEST_DATABASE_URL:
    DATABASE_FILE = os.path.join(tempfile.mkdtemp(prefix="dbs-scaling-"), "manager.sqlite3")
    DATABASES = {"default": {**sqlite_database(DATABASE_FILE), "TEST": {"NAME": DATABASE_FILE}}}
