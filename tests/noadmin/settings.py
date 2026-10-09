"""A project that installs DBS without django.contrib.admin."""

import tempfile

SECRET_KEY = "dbs-no-admin-secret-key"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "dbs",
    "tests.testapp",
]

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "dbs.security.middleware.DBSSecurityMiddleware",
]

ROOT_URLCONF = "tests.noadmin.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {},
    }
]

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

MEDIA_ROOT = tempfile.mkdtemp(prefix="dbs-no-admin-media-")

USE_TZ = True

DBS_SCHEDULER = "off"
