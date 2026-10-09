from functools import partial
from uuid import uuid4

import pytest
from rest_framework.test import APIClient

from dbs.manager.accounts.repositories import UserRepository
from tests.manager.support import PASSWORD


@pytest.fixture(autouse=True)
def own_cache(settings):
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": f"test-{uuid4()}",
        }
    }


@pytest.fixture(autouse=True)
def data_dir(settings, tmp_path_factory):
    home = tmp_path_factory.mktemp("manager-home")
    (home / "keys").mkdir()
    settings.DBS_MANAGER_DATA_DIR = str(home)
    settings.BACKUP_STORAGE_DIR = str(home / "backups")
    return home


@pytest.fixture
def admin(db):
    return UserRepository().create(username="sara", password=PASSWORD)


@pytest.fixture
def api(admin):
    client = APIClient()
    client.force_login(admin)
    return client


@pytest.fixture
def run_jobs(django_capture_on_commit_callbacks):
    return partial(django_capture_on_commit_callbacks, execute=True)


@pytest.fixture
def anonymous():
    return APIClient()
