from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, TypedDict
from uuid import UUID

from rest_framework.exceptions import NotFound

from dbs.manager.servers.exceptions import PassphraseMissing
from dbs.manager.servers.gateways import Credentials, DbsProfile, RemoteHost, connect
from dbs.manager.servers.models import Server
from dbs.manager.servers.repositories import ServerRepository
from dbs.manager.servers.services import vault_contexts
from dbs.manager.vault import unseal_text

if TYPE_CHECKING:
    from django.contrib.auth.models import AnonymousUser, User


class _Address(TypedDict):
    host: str
    port: int
    username: str
    host_key: str
    remote_dir: str


def _unsealed(token: bytes | memoryview | None, context: str) -> str | None:
    return None if token is None else unseal_text(token, context=context)


class ServerConnectionService:
    def __init__(self, user: User | AnonymousUser | None) -> None:
        self.user: User | AnonymousUser | None = user
        self.servers = ServerRepository()

    def credentials(self, server: Server) -> Credentials:
        address: _Address = {
            "host": server.host,
            "port": server.port,
            "username": server.username,
            "host_key": server.host_key,
            "remote_dir": server.remote_backup_dir,
        }
        if server.auth_method == Server.AuthMethod.KEY:
            return Credentials(
                **address,
                private_key=_unsealed(
                    server.private_key_sealed, vault_contexts.PRIVATE_KEY
                ),
                key_passphrase=_unsealed(
                    server.key_passphrase_sealed, vault_contexts.KEY_PASSPHRASE
                ),
            )
        return Credentials(
            **address,
            password=_unsealed(server.password_sealed, vault_contexts.PASSWORD),
        )

    @contextmanager
    def open(self, server: Server | UUID) -> Iterator[RemoteHost]:
        if not isinstance(server, Server):
            server = self._active(server)
        with connect(self.credentials(server)) as remote:
            yield remote

    def dbs_profile(self, server: Server) -> DbsProfile:
        return DbsProfile(
            python=server.python_path,
            manage=server.manage_path,
            project_dir=server.project_dir or None,
            settings_module=server.settings_module or None,
        )

    def backup_passphrase(self, server: Server) -> str:
        if server.backup_passphrase_sealed is None:
            raise PassphraseMissing()
        return unseal_text(
            server.backup_passphrase_sealed, context=vault_contexts.BACKUP_PASSPHRASE
        )

    def _active(self, server_id: UUID) -> Server:
        server = self.servers.find(server_id)
        if server is None:
            raise NotFound()
        return server
