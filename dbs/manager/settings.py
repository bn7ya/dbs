from __future__ import annotations

import os

from dbs.manager import paths
from dbs.manager.conf import DATABASE_URL_ENV, HOST_ENV, LOCAL_HOSTS
from dbs.manager.database import parse_database_url, sqlite_database

DBS_MANAGER_DATA_DIR = str(paths.ensure_data_dir(paths.resolve_data_dir()))
SECRET_KEY = paths.read_key(DBS_MANAGER_DATA_DIR)
DEBUG = False

DBS_MANAGER_HOST = os.environ.get(HOST_ENV, "").strip()
ALLOWED_HOSTS = list(LOCAL_HOSTS)
if DBS_MANAGER_HOST and DBS_MANAGER_HOST not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(DBS_MANAGER_HOST)

ROOT_URLCONF = "dbs.manager.urls"
WSGI_APPLICATION = "dbs.manager.wsgi.application"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "rest_framework",
    "dbs",
    "dbs.manager",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "dbs.manager.middleware.RequestOriginMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": (
        parse_database_url(os.environ[DATABASE_URL_ENV])
        if os.environ.get(DATABASE_URL_ENV)
        else sqlite_database(paths.database_path(DBS_MANAGER_DATA_DIR))
    )
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "dbs-manager",
    }
}

SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = 8 * 60 * 60
SESSION_COOKIE_NAME = "dbs_manager_session"
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_NAME = "csrftoken"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_PAGINATION_CLASS": "dbs.manager.common.pagination.DefaultPagination",
    "PAGE_SIZE": 25,
    "EXCEPTION_HANDLER": "dbs.manager.common.exceptions.exception_handler",
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTH_FAILURES_PER_USER = 5
AUTH_FAILURES_PER_ADDRESS = 20
AUTH_FAILURE_WINDOW = 900

LANGUAGE_CODE = "en"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"

DBS_SCHEDULER = "off"
DBS_EXCLUDE_MODELS = ["-dbs.auditevent", "-dbs.backuprecord"]
DBS_MANAGER_JOBS_INLINE = False

SSH_CONNECT_TIMEOUT = 15.0
SSH_COMMAND_TIMEOUT = 20.0
BACKUP_STORAGE_DIR = str(paths.backups_path(DBS_MANAGER_DATA_DIR))
BACKUP_EXEC_TIMEOUT = 3600.0
BACKUP_TASK_TIME_LIMIT = 6 * 60 * 60
BACKUP_GRACE_DAYS = 7
BACKUP_UPLOAD_MAX_BYTES = 5 * 1024**3
FILES_UPLOAD_MAX_BYTES = 2 * 1024**3
ENV_MAX_BYTES = 256 * 1024

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "{asctime} {levelname} {name} {message}", "style": "{"},
    },
    "handlers": {
        "file": {
            "class": "logging.FileHandler",
            "filename": str(paths.log_path(DBS_MANAGER_DATA_DIR)),
            "formatter": "plain",
            "encoding": "utf-8",
        },
    },
    "root": {"handlers": ["file"], "level": "INFO"},
}
