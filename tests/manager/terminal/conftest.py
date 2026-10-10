from __future__ import annotations

import io
import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest

from dbs.manager import cli
from dbs.manager.servers.gateways import RemoteHost
from dbs.manager.servers.models import Server
from dbs.manager.servers.services import ServerService
from dbs.manager.terminal import session
from tests.manager.servers.support import (
    BACKUP_DIR,
    BACKUP_PASSPHRASE,
    PROJECT_DIR,
    PYTHON,
    SETTINGS_MODULE,
    LocalSftpSession,
    host_key_line,
    private_key_text,
)

CONNECT = "dbs.manager.servers.services.connection_service.connect"


@dataclass
class Ran:
    code: int
    out: str
    err: str

    def json(self):
        return json.loads(self.out)


@pytest.fixture(autouse=True)
def storage(settings, tmp_path) -> Path:
    root = tmp_path / "backups"
    settings.BACKUP_STORAGE_DIR = str(root)
    return root


@pytest.fixture
def terminal(monkeypatch, capsys):
    monkeypatch.setattr(cli, "setup_django", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "resolve", lambda args: None)

    def run(*argv, stdin: str = "") -> Ran:
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
        code = cli.main([str(arg) for arg in argv])
        captured = capsys.readouterr()
        return Ran(code, captured.out, captured.err)

    return run


@pytest.fixture
def typing(monkeypatch):
    answers: list[str] = []
    monkeypatch.setattr(session, "interactive", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": answers.pop(0))
    monkeypatch.setattr(session.getpass, "getpass", lambda prompt="": answers.pop(0))
    return answers


@pytest.fixture
def make_server(admin):

    def make(name: str = "web-1", host: str = "10.0.0.5", **fields) -> Server:
        values = {
            "name": name,
            "host": host,
            "port": 2222,
            "username": "deploy",
            "auth_method": Server.AuthMethod.KEY,
            "private_key": private_key_text(),
            "host_key": host_key_line(),
            "project_dir": PROJECT_DIR,
            "python_path": PYTHON,
            "settings_module": SETTINGS_MODULE,
            "remote_backup_dir": BACKUP_DIR,
            "backup_passphrase": BACKUP_PASSPHRASE,
        }
        return ServerService(admin).create(**{**values, **fields})

    return make


@pytest.fixture
def local_host(monkeypatch):

    @contextmanager
    def connect(credentials) -> Iterator[RemoteHost]:
        sftp = LocalSftpSession()
        try:
            yield RemoteHost(sftp)
        finally:
            sftp.close()

    monkeypatch.setattr(CONNECT, connect)
