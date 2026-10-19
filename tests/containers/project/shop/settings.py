import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
if ENV_FILE.is_file():
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        name, separator, value = line.partition("=")
        if separator and name.strip() and not name.lstrip().startswith("#"):
            os.environ.setdefault(name.strip(), value.strip())

SECRET_KEY = os.environ.get("SHOP_SECRET_KEY", "dbs-live-container-secret")
DEBUG = False
ALLOWED_HOSTS = ["*"]
USE_TZ = True
ROOT_URLCONF = "shop.urls"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "dbs",
    "notes",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("SHOP_DATABASE", "/app/data/db.sqlite3"),
    }
}

DBS_BACKUP_DIR = os.environ.get("SHOP_BACKUP_DIR", "/var/backups/dbs")
DBS_BACKUP_PREFIX = "shop"
