from __future__ import annotations

from collections.abc import Callable
from functools import partial
from pathlib import Path

import pytest
from rest_framework.test import APIClient

from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.backups.models import BackupFile, BackupPlan
from dbs.manager.backups.repositories import BackupFileRepository
from dbs.manager.backups.services import BackupPlanService, BackupService
from dbs.manager.servers.models import Server
from dbs.manager.servers.services import ServerService
from tests.manager.backups.support import BackupHost, server_tree
from tests.manager.servers.support import (
    BACKUP_DIR,
    BACKUP_PASSPHRASE,
    PASSWORD,
    PROJECT_DIR,
    PYTHON,
    SETTINGS_MODULE,
    connecting_to,
    host_key_line,
    private_key_text,
)

CONNECT = "dbs.manager.servers.services.connection_service.connect"


@pytest.fixture(autouse=True)
def storage(settings, tmp_path) -> Path:
    root = tmp_path / "backups"
    settings.BACKUP_STORAGE_DIR = str(root)
    return root


@pytest.fixture
def run_jobs(django_capture_on_commit_callbacks):
    return partial(django_capture_on_commit_callbacks, execute=True)


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
        port=2222,
        username="deploy",
        auth_method=Server.AuthMethod.KEY,
        private_key=private_key,
        host_key=host_key_line(),
        project_dir=PROJECT_DIR,
        python_path=PYTHON,
        settings_module=SETTINGS_MODULE,
        remote_backup_dir=BACKUP_DIR,
        backup_passphrase=BACKUP_PASSPHRASE,
    )


@pytest.fixture
def server_root(tmp_path) -> Path:
    root = tmp_path / "server"
    server_tree(root)
    return root


@pytest.fixture
def host(monkeypatch, server_root) -> BackupHost:
    host = BackupHost(root=server_root)
    monkeypatch.setattr(CONNECT, connecting_to(host))
    return host


@pytest.fixture
def entry() -> Callable:
    return lambda activity_id: ActivityRepository().get(activity_id)


@pytest.fixture
def taken(admin, server, host, run_jobs, entry) -> Callable[[], BackupFile]:

    def take() -> BackupFile:
        with run_jobs():
            job = BackupService(admin).take(server.pk)
        return BackupFileRepository().get(entry(job.pk).data["backup"])

    return take


@pytest.fixture
def make_plan(admin, server) -> Callable[..., BackupPlan]:

    def make(**fields) -> BackupPlan:
        values = {
            "account_password": PASSWORD,
            "server": server.pk,
            "name": "django-dbs",
            "kind": "dbs",
            "interval_minutes": 1440,
            "keep": 7,
            "keep_remote": 1,
            "enabled": True,
        }
        return BackupPlanService(admin).create(**(values | fields))

    return make


@pytest.fixture
def ran(admin, host, run_jobs, entry) -> Callable:

    def run(plan: BackupPlan):
        with run_jobs():
            job = BackupPlanService(admin).run(plan.pk)
        return entry(job.pk)

    return run
