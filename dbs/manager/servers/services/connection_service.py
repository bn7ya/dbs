from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager, suppress
from datetime import timedelta
from typing import TYPE_CHECKING, TypedDict
from uuid import UUID

from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound

from dbs.manager.activity import heartbeat
from dbs.manager.servers import settling
from dbs.manager.servers.exceptions import (
    HostKeyChanged,
    PassphraseMissing,
    RemoteCommandFailed,
    ServerConnectionLost,
    SSHAuthFailed,
    SSHUnreachable,
)
from dbs.manager.servers.gateways import (
    ComposeService,
    Credentials,
    DbsProfile,
    RemoteHost,
    connect,
)
from dbs.manager.servers.models import Server
from dbs.manager.servers.repositories import ServerRepository
from dbs.manager.servers.services import vault_contexts
from dbs.manager.servers.services.liveness_service import ServerLiveness
from dbs.manager.vault import unseal_text

if TYPE_CHECKING:
    from django.contrib.auth.models import AnonymousUser, User

    from dbs.manager.activity.heartbeat import Pulse

CONNECTION_ERRORS = (HostKeyChanged, SSHAuthFailed, SSHUnreachable)
PROBE_EVERY = timedelta(minutes=5)
PROBE_COMMAND = ["true"]

_probing: set[UUID] = set()
_probing_lock = threading.Lock()


class _Address(TypedDict):
    host: str
    port: int
    username: str
    host_key: str
    remote_dir: str
    timeout_on_host: bool
    timeout_in_container: bool


def _unsealed(token: bytes | memoryview | None, context: str) -> str | None:
    return None if token is None else unseal_text(token, context=context)


class ServerConnectionService:
    def __init__(self, user: User | AnonymousUser | None) -> None:
        self.user: User | AnonymousUser | None = user
        self.servers = ServerRepository()
        self.liveness = ServerLiveness()

    def credentials(self, server: Server, pulse: Pulse | None = None) -> Credentials:
        address: _Address = {
            "host": server.host,
            "port": server.port,
            "username": server.username,
            "host_key": server.host_key,
            "remote_dir": server.remote_backup_dir,
            "timeout_on_host": bool(server.timeout_on_host),
            "timeout_in_container": bool(server.timeout_in_container)
            and server.in_compose,
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
                on_activity=pulse,
            )
        return Credentials(
            **address,
            password=_unsealed(server.password_sealed, vault_contexts.PASSWORD),
            on_activity=pulse,
        )

    @contextmanager
    def open(self, server: Server | UUID) -> Iterator[RemoteHost]:
        if not isinstance(server, Server):
            server = self._active(server)
        pulse = heartbeat.current()
        try:
            with ExitStack() as stack:
                try:
                    remote = stack.enter_context(
                        connect(self.credentials(server, pulse))
                    )
                except CONNECTION_ERRORS as exc:
                    self.liveness.offline(server, exc)
                    raise
                self.liveness.online(server)
                if pulse is not None:
                    stack.enter_context(pulse.connected())
                yield remote
        except RemoteCommandFailed as exc:
            self._interrupted(server, exc)
            raise
        self.liveness.online(server)

    def probe(self, server: Server) -> bool:
        if self._seen_lately(server):
            return False
        with _probing_lock:
            if server.pk in _probing:
                return False
            _probing.add(server.pk)
        try:
            with suppress(APIException), self.open(server) as remote:
                remote.run(PROBE_COMMAND)
        finally:
            with _probing_lock:
                _probing.discard(server.pk)
        return True

    def dbs_profile(self, server: Server) -> DbsProfile:
        return DbsProfile(
            python=server.python_path,
            manage=server.manage_path,
            project_dir=server.project_dir or None,
            settings_module=server.settings_module or None,
            compose=(
                ComposeService(
                    service=server.compose_service,
                    files=tuple(server.compose_files),
                )
                if server.in_compose
                else None
            ),
        )

    def backup_passphrase(self, server: Server) -> str:
        if server.backup_passphrase_sealed is None:
            raise PassphraseMissing()
        return unseal_text(
            server.backup_passphrase_sealed, context=vault_contexts.BACKUP_PASSPHRASE
        )

    def _interrupted(self, server: Server, exc: RemoteCommandFailed) -> None:
        if exc.settles_at is not None:
            settling.mark(server.pk, exc.settles_at)
        if isinstance(exc, ServerConnectionLost):
            self.liveness.offline(server, exc)

    def _seen_lately(self, server: Server) -> bool:
        return (
            server.connection_state == Server.ConnectionState.ONLINE
            and server.last_seen_at is not None
            and timezone.now() - server.last_seen_at < PROBE_EVERY
        )

    def _active(self, server_id: UUID) -> Server:
        server = self.servers.find(server_id)
        if server is None:
            raise NotFound()
        return server


def probe_servers() -> int:
    connections = ServerConnectionService(None)
    return sum(
        connections.probe(server)
        for server in ServerRepository().active().order_by("name")
    )
