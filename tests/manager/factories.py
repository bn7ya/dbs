from __future__ import annotations

from typing import Any

from dbs.manager.applications.models import Application
from dbs.manager.applications.services import ApplicationService
from dbs.manager.servers.models import Server
from dbs.manager.servers.services import ServerService
from tests.manager.servers.support import host_key_line, private_key_text

SERVER_FIELDS = frozenset(
    {
        "host",
        "port",
        "username",
        "auth_method",
        "private_key",
        "key_passphrase",
        "password",
        "host_key",
    }
)


def make_server(user: Any, name: str = "web-1", host: str = "10.0.0.5", **fields) -> Server:
    values = {
        "name": name,
        "host": host,
        "port": 2222,
        "username": "deploy",
        "auth_method": Server.AuthMethod.KEY,
        "private_key": private_key_text(),
        "host_key": host_key_line(),
    }
    return ServerService(user).create(**{**values, **fields})


def make_application(
    user: Any,
    name: str = "web-1",
    host: str = "10.0.0.5",
    *,
    server: Server | None = None,
    **fields,
) -> Application:
    reach = {key: value for key, value in fields.items() if key in SERVER_FIELDS}
    settings = {key: value for key, value in fields.items() if key not in SERVER_FIELDS}
    if server is None:
        server = make_server(user, name=name, host=host, **reach)
    return ApplicationService(user).create(server=server.pk, name=name, **settings)
