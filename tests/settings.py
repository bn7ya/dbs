"""Minimal Django settings for the DBS test suite."""

import os
import tempfile

SECRET_KEY = "dbs-test-secret-key"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "dbs",
    "tests.testapp",
    "tests.complexapp",
]

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
]

ROOT_URLCONF = "tests.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.csrf",
            ]
        },
    }
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Sequence handling is backend specific, so the suite can run against PostgreSQL
# with DBS_TEST_DB=postgres (see tests/test_sequences.py).
if os.environ.get("DBS_TEST_DB") == "postgres":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DBS_TEST_PG_NAME", "dbs_test"),
            "USER": os.environ.get("DBS_TEST_PG_USER", "postgres"),
            "PASSWORD": os.environ.get("DBS_TEST_PG_PASSWORD", ""),
            "HOST": os.environ.get("DBS_TEST_PG_HOST", "localhost"),
            "PORT": os.environ.get("DBS_TEST_PG_PORT", "5432"),
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# A throwaway media root so FileField round-trips have somewhere to live.
MEDIA_ROOT = tempfile.mkdtemp(prefix="dbs-media-")

USE_TZ = True
