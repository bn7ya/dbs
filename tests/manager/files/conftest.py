from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from rest_framework.test import APIClient

from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.servers.gateways import RemoteHost
from dbs.manager.servers.models import Server
from dbs.manager.servers.services import ServerService
from tests.manager.servers.support import (
    PASSWORD,
    LocalSftpSession,
    host_key_line,
    private_key_text,
)
from tests.manager.support import logged_entries

CONNECT = "dbs.manager.servers.services.connection_service.connect"


@dataclass
class Tree:
    base: Path
    media: Path = field(init=False)
    backups: Path = field(init=False)
    outside: Path = field(init=False)
    alias: Path = field(init=False)

    def __post_init__(self) -> None:
        self.media = self.base / "srv" / "app" / "media"
        self.backups = self.base / "var" / "backups" / "e2e"
        self.outside = self.base / "etc"
        self.alias = self.base / "alias"

    @property
    def roots(self) -> list[str]:
        return [str(self.media), str(self.backups), str(self.alias)]


@pytest.fixture(autouse=True)
def storage(settings, tmp_path) -> Path:
    root = tmp_path / "backups"
    settings.BACKUP_STORAGE_DIR = str(root)
    return root


@pytest.fixture(autouse=True)
def umask():
    before = os.umask(0o022)
    yield
    os.umask(before)


@pytest.fixture
def tree(tmp_path) -> Tree:
    files = Tree(tmp_path.resolve() / "server")
    files.media.mkdir(parents=True)
    files.backups.mkdir(parents=True)
    files.outside.mkdir(parents=True)
    (files.outside / "passwd").write_bytes(b"root:x:0:0")
    (files.media / "logo.png").write_bytes(b"\x89PNG not really")
    (files.media / "Readme.md").write_bytes(b"# media")
    (files.media / "Docs").mkdir()
    (files.media / "Docs" / "report.pdf").write_bytes(b"%PDF-1.7")
    (files.media / "assets").mkdir()
    (files.media / "shared").mkdir()
    (files.media / "escape").symlink_to(files.outside)
    (files.media / "secret-link").symlink_to(files.outside / "passwd")
    (files.media / "docs-link").symlink_to(files.media / "Docs")
    (files.media / "logo-link").symlink_to(files.media / "logo.png")
    files.alias.symlink_to(files.media / "shared")
    (files.backups / "db.sql.gz").write_bytes(b"dump")
    return files


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
def server(admin, tree) -> Server:
    return ServerService(admin).create(
        name="web-1",
        host="10.0.0.5",
        port=2222,
        username="deploy",
        auth_method=Server.AuthMethod.KEY,
        private_key=private_key_text(),
        host_key=host_key_line(),
        file_roots=tree.roots,
    )


@pytest.fixture
def sessions(monkeypatch) -> list[LocalSftpSession]:
    opened: list[LocalSftpSession] = []

    @contextmanager
    def connect(credentials) -> Iterator[RemoteHost]:
        session = LocalSftpSession()
        opened.append(session)
        try:
            yield RemoteHost(session)
        finally:
            session.close()

    monkeypatch.setattr(CONNECT, connect)
    return opened


@pytest.fixture
def logged():
    return logged_entries
