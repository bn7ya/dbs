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
from dbs.manager.applications.models import Application
from dbs.manager.servers.gateways import (
    ContainerTarget,
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
STAGING_FOLDER = ".dbs-staging"

_probing: set[UUID] = set()
_probing_lock = threading.Lock()


class _Address(TypedDict):
    host: str
    port: int
    username: str
    host_key: str
    timeout_on_host: bool
    timeout_in_container: bool


def _unsealed(token: bytes | memoryview | None, context: str) -> str | None:
    return None if token is None else unseal_text(token, context=context)


class ServerConnectionService:
    def __init__(self, user: User | AnonymousUser | None) -> None:
        self.user: User | AnonymousUser | None = user
        self.servers = ServerRepository()
        self.liveness = ServerLiveness()

    def credentials(
        self,
        server: Server,
        pulse: Pulse | None = None,
        application: Application | None = None,
    ) -> Credentials:
        address: _Address = {
            "host": server.host,
            "port": server.port,
            "username": server.username,
            "host_key": server.host_key,
            "timeout_on_host": bool(server.timeout_on_host),
            "timeout_in_container": application is not None
            and application.in_container
            and bool(application.timeout_in_container),
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
    def open(self, target: Server | Application | UUID) -> Iterator[RemoteHost]:
        application = target if isinstance(target, Application) else None
        server = (
            target.server
            if isinstance(target, Application)
            else target
            if isinstance(target, Server)
            else self._active(target)
        )
        pulse = heartbeat.current()
        try:
            with ExitStack() as stack:
                try:
                    remote = stack.enter_context(
                        connect(self.credentials(server, pulse, application))
                    )
                except CONNECTION_ERRORS as exc:
                    self.liveness.offline(server, exc)
                    raise
                self.liveness.online(server)
                if pulse is not None:
                    stack.enter_context(pulse.connected())
                yield remote
        except RemoteCommandFailed as exc:
            self._interrupted(server, application, exc)
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

    def dbs_profile(self, application: Application) -> DbsProfile:
        return DbsProfile(
            python=application.python_path,
            manage=application.manage_path,
            project_dir=application.project_dir or None,
            settings_module=application.settings_module or None,
            container=container_of(application),
        )

    def backup_passphrase(self, application: Application) -> str:
        if application.backup_passphrase_sealed is None:
            raise PassphraseMissing()
        return unseal_text(
            application.backup_passphrase_sealed,
            context=vault_contexts.BACKUP_PASSPHRASE,
        )

    def staging_folder(self, application: Application, remote: RemoteHost) -> str:
        if application.in_container:
            return remote.home_folder(STAGING_FOLDER)
        return application.remote_backup_dir

    def _interrupted(
        self,
        server: Server,
        application: Application | None,
        exc: RemoteCommandFailed,
    ) -> None:
        if exc.settles_at is not None:
            settling.mark((application or server).pk, exc.settles_at)
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


def container_of(application: Application) -> ContainerTarget | None:
    if not application.in_container:
        return None
    compose = application.kind == Application.Kind.COMPOSE
    return ContainerTarget(
        engine=application.engine or Application.Engine.DOCKER,
        service=application.compose_service if compose else "",
        files=tuple(application.compose_files) if compose else (),
        project=application.compose_project if compose else "",
        container="" if compose else application.container_name,
        workdir=application.workdir,
    )


def probe_servers() -> int:
    connections = ServerConnectionService(None)
    return sum(
        connections.probe(server)
        for server in ServerRepository().active().order_by("name")
    )
