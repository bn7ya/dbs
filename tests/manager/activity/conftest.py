from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.applications.models import Application
from dbs.manager.applications.services import ApplicationService
from dbs.manager.servers.models import Server
from dbs.manager.servers.services import ServerService
from tests.manager.servers.support import (
    BACKUP_DIR,
    BACKUP_PASSPHRASE,
    ENV_PATH,
    KEY_PASSPHRASE,
    MEDIA_ROOT,
    PASSWORD,
    PROJECT_DIR,
    PYTHON,
    host_key_line,
    private_key_text,
)


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
def private_key() -> str:
    return private_key_text()


@pytest.fixture
def server(admin, private_key) -> Server:
    return ServerService(admin).create(
        name="web-1",
        host="10.0.0.5",
        username="deploy",
        auth_method=Server.AuthMethod.KEY,
        private_key=private_key,
        key_passphrase=KEY_PASSPHRASE,
        host_key=host_key_line(),
    )


@pytest.fixture
def application(admin, server) -> Application:
    return ApplicationService(admin).create(
        server=server.pk,
        name="shop",
        project_dir=PROJECT_DIR,
        python_path=PYTHON,
        env_path=ENV_PATH,
        file_roots=[MEDIA_ROOT],
        remote_backup_dir=BACKUP_DIR,
        backup_passphrase=BACKUP_PASSPHRASE,
    )


@pytest.fixture
def logged():

    def entries(action=None):
        return list(ActivityRepository().filtered(action=action))

    return entries
