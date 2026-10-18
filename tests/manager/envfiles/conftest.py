from __future__ import annotations

import os
import shlex
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from rest_framework.test import APIClient

from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.applications.models import Application
from dbs.manager.envfiles.models import EnvVersion
from dbs.manager.envfiles.repositories import EnvVersionRepository
from dbs.manager.servers.exceptions import SSHUnreachable
from dbs.manager.servers.gateways import RemoteHost
from dbs.transports import RemoteResult
from tests.manager.factories import make_application as application_for
from tests.manager.servers.support import PASSWORD, LocalSftpSession
from tests.manager.support import logged_entries

CONNECT = "dbs.manager.servers.services.connection_service.connect"
LIST = "/api/envfiles/"
CONTAINER = "shop-web"
EXEC_OPTIONS_WITH_VALUE = frozenset({"-u", "-w", "-e"})

SECRET = "sk_live_51f0c2e9a7d3b8"
DB_PASSWORD = "db-password-c4a19e72"
ENV = (
    f"# production\nSECRET_KEY={SECRET}\nDEBUG=0\n"
    f'export DATABASE_URL="postgres://app:{DB_PASSWORD}@db/app"\n'
).encode()


def argv_of(script: str) -> list[str]:
    body = shlex.split(script)[2]
    if body.startswith("exec "):
        return shlex.split(body[len("exec ") :])
    return shlex.split(body.split("\nexec ", 1)[1])


def in_container(argv: list[str]) -> tuple[str, list[str]]:
    engine, verb, *rest = argv
    assert (engine, verb) == ("docker", "exec"), argv
    while rest[0].startswith("-"):
        option = rest.pop(0)
        if option in EXEC_OPTIONS_WITH_VALUE:
            rest.pop(0)
    return rest[0], rest[1:]


class ContainerSession(LocalSftpSession):
    def __init__(self) -> None:
        super().__init__()
        self.runs: list[list[str]] = []
        self.feeds: list[list[str]] = []

    def run(self, script, stdin_line=None, timeout=None) -> RemoteResult:
        argv = argv_of(script)
        self.runs.append(argv)
        given = b"" if stdin_line is None else f"{stdin_line}\n".encode()
        return self._inside(argv, given)

    def feed(self, script, source, stdin_line=None, timeout=None) -> RemoteResult:
        argv = argv_of(script)
        self.feeds.append(argv)
        given = b"" if stdin_line is None else f"{stdin_line}\n".encode()
        return self._inside(argv, given + source.read())

    def _inside(self, argv: list[str], given: bytes) -> RemoteResult:
        container, command = in_container(argv)
        assert container == CONTAINER
        done = subprocess.run(command, input=given, capture_output=True, check=False)
        return RemoteResult(done.returncode, done.stdout.decode(), done.stderr.decode())


@dataclass
class Network:
    opened: list[ContainerSession] = field(default_factory=list)
    unreachable: set[str] = field(default_factory=set)

    @property
    def runs(self) -> list[list[str]]:
        return [argv for session in self.opened for argv in session.runs]

    @property
    def feeds(self) -> list[list[str]]:
        return [argv for session in self.opened for argv in session.feeds]


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
def container_env(tmp_path) -> Path:
    path = tmp_path.resolve() / "container" / "app" / ".env"
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
def make_application(admin) -> Callable[..., Application]:

    def make(name: str = "web-1", host: str = "10.0.0.5", **fields) -> Application:
        return application_for(admin, name=name, host=host, **fields)

    return make


@pytest.fixture
def application(make_application, env_file) -> Application:
    return make_application(env_path=str(env_file))


@pytest.fixture
def in_a_container(make_application) -> Callable[..., Application]:

    def make(env_path: str, **fields) -> Application:
        return make_application(
            name="shop",
            host="10.0.0.20",
            kind=Application.Kind.CONTAINER,
            engine=Application.Engine.DOCKER,
            container_name=CONTAINER,
            python_path=sys.executable,
            env_path=env_path,
            env_location=Application.EnvLocation.CONTAINER,
            **fields,
        )

    return make


@pytest.fixture
def network(monkeypatch) -> Network:
    state = Network()

    @contextmanager
    def connect(credentials) -> Iterator[RemoteHost]:
        if credentials.host in state.unreachable:
            raise SSHUnreachable()
        session = ContainerSession()
        state.opened.append(session)
        try:
            yield RemoteHost(session)
        finally:
            session.close()

    monkeypatch.setattr(CONNECT, connect)
    return state


@pytest.fixture
def pull(api, network) -> Callable[[Application], dict]:

    def pulled(application: Application) -> dict:
        response = api.post(f"{LIST}pull/", {"application": application.pk})
        assert response.status_code == 200, response.content
        return response.json()

    return pulled


@pytest.fixture
def versions() -> Callable[[Application], list[EnvVersion]]:
    return lambda application: list(
        EnvVersionRepository().for_application(application.pk)
    )


@pytest.fixture
def logged():
    return logged_entries
