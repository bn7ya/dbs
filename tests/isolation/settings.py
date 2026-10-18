import os
import tempfile

from tests.settings import *  # noqa: F401,F403
from tests.settings import DATABASES

DATABASE_FILE = os.environ.setdefault(
    "DBS_ISOLATION_DATABASE", os.path.join(tempfile.gettempdir(), f"dbs-isolation-{os.getpid()}.sqlite3")
)

if DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": DATABASE_FILE,
            "TEST": {"NAME": DATABASE_FILE},
        }
    }
else:
    DATABASES = {"default": dict(DATABASES["default"])}
    DATABASES["default"]["TEST"] = dict(
        DATABASES["default"].get("TEST", {}),
        NAME=DATABASES["default"]["NAME"] + "_isolation",
    )
    DATABASES["default"]["NAME"] = DATABASES["default"]["TEST"]["NAME"]

DBS_JOB_PROCESS = True
