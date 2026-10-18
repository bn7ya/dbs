from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from dbs.manager.applications.models import Application
from dbs.manager.applications.repositories import ApplicationRepository
from dbs.manager.servers.models import Server
from dbs.manager.servers.repositories import ServerRepository
from tests.manager.factories import make_application, make_server
from tests.manager.servers.support import (
    BACKUP_DIR,
    BACKUP_PASSPHRASE,
    ENV_PATH,
    MEDIA_ROOT,
    PROJECT_DIR,
    PYTHON,
    SETTINGS_MODULE,
    host_key_line,
    private_key_text,
)

SETUP_OVER = timedelta(hours=2)


@pytest.fixture
def host_key() -> str:
    return host_key_line()


@pytest.fixture
def private_key() -> str:
    return private_key_text()


@pytest.fixture
def server(admin, host_key, private_key) -> Server:
    found = make_server(admin, private_key=private_key, host_key=host_key)
    return ServerRepository().update(found, created_at=timezone.now() - SETUP_OVER)


@pytest.fixture
def new_server(admin) -> Server:
    return make_server(admin, name="new", host="10.0.0.5")


@pytest.fixture
def application(admin, server) -> Application:
    found = make_application(
        admin,
        server=server,
        project_dir=PROJECT_DIR,
        python_path=PYTHON,
        settings_module=SETTINGS_MODULE,
        remote_backup_dir=BACKUP_DIR,
        backup_passphrase=BACKUP_PASSPHRASE,
        file_roots=[MEDIA_ROOT],
        env_path=ENV_PATH,
    )
    return ApplicationRepository().update(found, created_at=timezone.now() - SETUP_OVER)
