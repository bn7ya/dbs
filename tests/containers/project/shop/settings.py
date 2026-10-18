import os

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
        "NAME": "/app/data/db.sqlite3",
    }
}

DBS_BACKUP_DIR = "/var/backups/dbs"
DBS_BACKUP_PREFIX = "shop"
