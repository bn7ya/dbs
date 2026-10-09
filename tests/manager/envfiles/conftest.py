from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from rest_framework.test import APIClient

from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.envfiles.models import EnvVersion
from dbs.manager.envfiles.repositories import EnvVersionRepository
from dbs.manager.servers.exceptions import SSHUnreachable
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
LIST = "/api/envfiles/"

SECRET = "sk_live_51f0c2e9a7d3b8"
DB_PASSWORD = "db-password-c4a19e72"
ENV = (
    f"# production\nSECRET_KEY={SECRET}\nDEBUG=0\n"
    f'export DATABASE_URL="postgres://app:{DB_PASSWORD}@db/app"\n'
).encode()


@dataclass
class Network:
    opened: list[LocalSftpSession] = field(default_factory=list)
    unreachable: set[str] = field(default_factory=set)


@pytest.fixture(autouse=True)
def umask():
    before = os.umask(0o022)
    yield
    os.umask(before)


@pytest.fixture
def env_file(tmp_path) -> Path:
    path = tmp_path.resolve() / "srv" / "app" / ".env"
    path.parent.mkdir(parents=True)
    path.write_bytes(ENV)
    path.chmod(0o640)
    return path


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
def make_server(admin) -> Callable[..., Server]:

    def make(name: str = "web-1", host: str = "10.0.0.5", **fields) -> Server:
        return ServerService(admin).create(
            name=name,
            host=host,
            port=2222,
            username="deploy",
            auth_method=Server.AuthMethod.KEY,
            private_key=private_key_text(),
            host_key=host_key_line(),
            **fields,
        )

    return make


@pytest.fixture
def server(make_server, env_file) -> Server:
    return make_server(env_path=str(env_file))


@pytest.fixture
def network(monkeypatch) -> Network:
    state = Network()

    @contextmanager
    def connect(credentials) -> Iterator[RemoteHost]:
        if credentials.host in state.unreachable:
            raise SSHUnreachable()
        session = LocalSftpSession()
        state.opened.append(session)
        try:
            yield RemoteHost(session)
        finally:
            session.close()

    monkeypatch.setattr(CONNECT, connect)
    return state


@pytest.fixture
def pull(api, network) -> Callable[[Server], dict]:

    def pulled(server: Server) -> dict:
        response = api.post(f"{LIST}pull/", {"server": server.pk})
        assert response.status_code == 200, response.content
        return response.json()

    return pulled


@pytest.fixture
def versions() -> Callable[[Server], list[EnvVersion]]:
    return lambda server: list(EnvVersionRepository().for_server(server.pk))


@pytest.fixture
def logged():
    return logged_entries
