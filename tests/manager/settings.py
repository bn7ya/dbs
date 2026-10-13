import os
import tempfile

os.environ["DBS_MANAGER_HOME"] = tempfile.mkdtemp(prefix="dbs-manager-test-")
TEST_DATABASE_URL = os.environ.pop("DBS_MANAGER_DATABASE_URL", "")

from dbs.manager.database import parse_database_url  # noqa: E402
from dbs.manager.settings import *  # noqa: E402,F403

DATABASES = {
    "default": (
        parse_database_url(TEST_DATABASE_URL)
        if TEST_DATABASE_URL
        else {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
    )
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

DBS_MANAGER_JOBS_INLINE = True

LOGGING = {"version": 1, "disable_existing_loggers": False}
