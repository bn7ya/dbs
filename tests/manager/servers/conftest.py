from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.applications.models import Application
from dbs.manager.applications.repositories import ApplicationRepository
from dbs.manager.servers.models import Server
from dbs.manager.servers.repositories import ServerRepository
from tests.manager.factories import make_application, make_server
from tests.manager.servers.support import (
    BACKUP_DIR,
    BACKUP_PASSPHRASE,
    ENV_PATH,
    KEY_PASSPHRASE,
    MEDIA_ROOT,
    PASSWORD,
    PROJECT_DIR,
    PYTHON,
    SETTINGS_MODULE,
    host_key_line,
    private_key_text,
)

SETUP_OVER = timedelta(hours=2)


@pytest.fixture
def admin(db):
    return UserRepository().create(username="sara", password=PASSWORD)


@pytest.fixture
def api(admin) -> APIClient:
    client = APIClient()
    client.force_login(admin)
    return client


@pytest.fixture
def anonymous() -> APIClient:
    return APIClient()


@pytest.fixture
def host_key() -> str:
    return host_key_line()


@pytest.fixture
def private_key() -> str:
    return private_key_text()


@pytest.fixture
def configured_server(admin, host_key, private_key) -> Server:
    server = make_server(
        admin,
        private_key=private_key,
        key_passphrase=KEY_PASSPHRASE,
        host_key=host_key,
    )
    return ServerRepository().update(server, created_at=timezone.now() - SETUP_OVER)


@pytest.fixture
def configured_application(admin, configured_server) -> Application:
    application = make_application(
        admin,
        server=configured_server,
        project_dir=PROJECT_DIR,
        python_path=PYTHON,
        settings_module=SETTINGS_MODULE,
        remote_backup_dir=BACKUP_DIR,
        backup_passphrase=BACKUP_PASSPHRASE,
        file_roots=[MEDIA_ROOT],
        env_path=ENV_PATH,
    )
    return ApplicationRepository().update(
        application, created_at=timezone.now() - SETUP_OVER
    )
