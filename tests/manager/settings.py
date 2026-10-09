import os
import tempfile

os.environ["DBS_MANAGER_HOME"] = tempfile.mkdtemp(prefix="dbs-manager-test-")
os.environ.pop("DBS_MANAGER_DATABASE_URL", None)

from dbs.manager.settings import *  # noqa: E402,F403

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

DBS_MANAGER_JOBS_INLINE = True

LOGGING = {"version": 1, "disable_existing_loggers": False}
