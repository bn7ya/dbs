import json
import os

SECRET_KEY = os.environ.get("PROJECT_SECRET_KEY", "one-secret-key-shared-by-two-projects")
DEBUG = False
USE_TZ = True
ROOT_URLCONF = "shop.urls"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "dbs",
    "ledger",
]

DATABASES = {"default": json.loads(os.environ["PROJECT_DATABASE"])}

DBS_BACKUP_DIR = os.environ.get("PROJECT_BACKUP_DIR") or None
DBS_BACKUP_PREFIX = "shop"
DBS_SCHEDULER = "off"
DBS_KDF_TIME_COST = 1
DBS_KDF_MEMORY_COST = 8 * 1024
DBS_KDF_PARALLELISM = 1

if os.environ.get("PROJECT_MAX_BACKUPS"):
    DBS_MAX_BACKUPS = int(os.environ["PROJECT_MAX_BACKUPS"])
if os.environ.get("PROJECT_CHECKPOINTS") == "off":
    DBS_MIGRATION_CHECKPOINTS = False
if os.environ.get("PROJECT_EXCLUDE_MODELS"):
    DBS_EXCLUDE_MODELS = os.environ["PROJECT_EXCLUDE_MODELS"].split(",")
if os.environ.get("PROJECT_APPLICATION"):
    DBS_APPLICATION = os.environ["PROJECT_APPLICATION"]
