from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

import pytest
from rest_framework.test import APIClient

from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.shell.sessions import SHELLS
from dbs.manager.shell.service import stop_terminals
from tests.fake_ssh import FakeTerminalChannel
from tests.manager.factories import make_application, make_server
from tests.manager.support import PASSWORD

CONNECT = "dbs.manager.servers.services.connection_service.connect"


@dataclass
class TerminalSession:
    opened: list[dict] = field(default_factory=list)
    channels: list[FakeTerminalChannel] = field(default_factory=list)
    closed: int = 0

    def open_terminal(self, command=None, *, term="xterm-256color", cols=80, rows=24):
        channel = FakeTerminalChannel()
        channel.get_pty(term=term, width=cols, height=rows)
        if command is None:
            channel.invoke_shell()
        else:
            channel.exec_command(command)
        self.opened.append({"command": command, "cols": cols, "rows": rows})
        self.channels.append(channel)
        return channel


@dataclass
class TerminalRemote:
    session: TerminalSession


@pytest.fixture(autouse=True)
def no_terminals_left(db):
    yield
    stop_terminals()
    SHELLS.sessions.clear()


@pytest.fixture
def ssh(monkeypatch) -> TerminalSession:
    found = TerminalSession()

    @contextmanager
    def connect(credentials) -> Iterator[TerminalRemote]:
        try:
            yield TerminalRemote(found)
        finally:
            found.closed += 1

    monkeypatch.setattr(CONNECT, connect)
    return found


@pytest.fixture
def server(admin):
    return make_server(admin)


@pytest.fixture
def host_application(admin, server):
    return make_application(
        admin, "shop", server=server, project_dir="/srv/shop", python_path="/srv/shop/.venv/bin/python"
    )


@pytest.fixture
def compose_application(admin, server):
    return make_application(
        admin,
        "blog",
        server=server,
        kind="compose",
        engine="podman",
        compose_service="web",
        compose_files=["compose.prod.yaml"],
        project_dir="/srv/blog",
        workdir="/app",
        python_path="python3",
    )


@pytest.fixture
def container_application(admin, server):
    return make_application(
        admin,
        "wiki",
        server=server,
        kind="container",
        engine="docker",
        container_name="wiki-web",
        python_path="python3",
    )


@pytest.fixture
def other(db):
    return UserRepository().create(username="omar", password=PASSWORD)


@pytest.fixture
def other_api(other):
    client = APIClient()
    client.force_login(other)
    return client


def opened(api, **body):
    return api.post(
        "/api/terminals/", {"password": PASSWORD, **body}, format="json"
    )


def output(api, identifier, cursor=0):
    return api.get(f"/api/terminals/{identifier}/output/", {"cursor": cursor})
