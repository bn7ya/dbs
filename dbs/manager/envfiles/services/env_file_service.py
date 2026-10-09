from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast
from uuid import UUID

from django.conf import settings
from django.db.models import QuerySet
from django.views.decorators.debug import sensitive_variables
from rest_framework.exceptions import NotFound

from dbs.manager.accounts.services import AccountService
from dbs.manager.activity.services import ActivityService
from dbs.manager.envfiles import dotenv
from dbs.manager.envfiles.exceptions import (
    DifferentServers,
    EnvPathMissing,
    EnvTooLarge,
)
from dbs.manager.envfiles.models import EnvVersion
from dbs.manager.envfiles.repositories import EnvVersionRepository
from dbs.manager.envfiles.services import vault_contexts
from dbs.manager.servers.exceptions import FileTooLarge, RemoteNotFound
from dbs.manager.servers.models import Server
from dbs.manager.servers.services import ServerConnectionService, ServerService
from dbs.manager.vault import fingerprint, seal, unseal

if TYPE_CHECKING:
    from django.contrib.auth.models import AnonymousUser, User

    from dbs.manager.servers.gateways import RemoteEntry, RemoteHost

FILE = "file"
NEW_FILE_MODE = 0o600


class Action:
    PULL = "env.pull"
    REVEAL = "env.reveal"
    PUSH = "env.push"


@dataclass(frozen=True)
class Pulled:
    created: bool
    version: EnvVersion


@dataclass(frozen=True)
class Comparison:
    from_id: UUID
    to_id: UUID
    added: list[str]
    removed: list[str]
    changed: list[str]


class EnvFileService:
    def __init__(self, user: User | AnonymousUser | None) -> None:
        self.user: User | AnonymousUser | None = user
        self.versions = EnvVersionRepository()
        self.servers = ServerService(user)
        self.connections = ServerConnectionService(user)
        self.activity = ActivityService(user)

    def list(self, server_id: UUID) -> QuerySet[EnvVersion]:
        return self.versions.for_server(server_id)

    def get(self, version_id: UUID) -> EnvVersion:
        version = self.versions.find(version_id)
        if version is None:
            raise NotFound()
        return version

    @sensitive_variables()
    def compare(self, version_id: UUID, other_id: UUID) -> Comparison:
        source, target = self.get(version_id), self.get(other_id)
        if source.server_id != target.server_id:
            raise DifferentServers()
        found = dotenv.diff(_opened(source), _opened(target))
        return Comparison(
            from_id=source.pk,
            to_id=target.pk,
            added=found.added,
            removed=found.removed,
            changed=found.changed,
        )

    def pull(self, server_id: UUID) -> Pulled:
        return self._pull(self.servers.get(server_id), EnvVersion.Source.PULLED)

    def snapshot(self, server: Server) -> Pulled:
        return self._pull(server, EnvVersion.Source.SCHEDULED)

    @sensitive_variables()
    def reveal(self, version_id: UUID, password: str) -> str:
        version = self.get(version_id)
        with self.activity.track(
            Action.REVEAL, server=version.server, target=version.path
        ) as entry:
            entry.detail = {"version": str(version.pk)}
            AccountService(self.user).confirm_password(password)
            content = _opened(version)
        return content.decode("utf-8", errors="replace")

    @sensitive_variables()
    def push(self, version_id: UUID, password: str) -> EnvVersion:
        version = self.get(version_id)
        server = self.servers.get(version.server_id)
        with self.activity.track(
            Action.PUSH, server=server, target=server.env_path
        ) as entry:
            entry.detail = {"from_version": str(version.pk)}
            AccountService(self.user).confirm_password(password)
            return self._write(version, server)

    @sensitive_variables()
    def copy_to(self, version_id: UUID, server: Server) -> EnvVersion:
        version = self.get(version_id)
        with self.activity.track(
            Action.PUSH, server=server, target=server.env_path
        ) as entry:
            entry.detail = {"from_version": str(version.pk)}
            return self._write(version, server)

    @sensitive_variables()
    def _write(self, version: EnvVersion, server: Server) -> EnvVersion:
        path = _env_path(server)
        content = _opened(version)
        with self.connections.open(server) as remote:
            real = remote.realpath(path)
            current = _regular_file(remote, real)
            mode, owner = NEW_FILE_MODE, None
            if current is not None:
                self._keep(server, path, _read(remote, real), EnvVersion.Source.PULLED)
                mode = (
                    NEW_FILE_MODE
                    if current.permissions is None
                    else current.permissions
                )
                if current.uid is not None and current.gid is not None:
                    owner = (current.uid, current.gid)
            remote.replace_file(real, content, mode=mode, owner=owner)
        return self._store(server, path, content, EnvVersion.Source.PUSHED)

    @sensitive_variables()
    def _pull(self, server: Server, source: str) -> Pulled:
        with self.activity.track(
            Action.PULL, server=server, target=server.env_path
        ) as entry:
            path = _env_path(server)
            with self.connections.open(server) as remote:
                content = _read(remote, path)
            pulled = self._keep(server, path, content, source)
            entry.detail = {"created": pulled.created}
        return pulled

    @sensitive_variables()
    def _keep(self, server: Server, path: str, content: bytes, source: str) -> Pulled:
        newest = self.versions.newest_for(server.pk)
        made = fingerprint(content, context=vault_contexts.CONTENT)
        if newest is not None and newest.path == path and newest.fingerprint == made:
            return Pulled(created=False, version=newest)
        return Pulled(created=True, version=self._store(server, path, content, source))

    @sensitive_variables()
    def _store(
        self, server: Server, path: str, content: bytes, source: str
    ) -> EnvVersion:
        return self.versions.create(
            created_by=cast("User | None", self.user),
            server=server,
            path=path,
            content_sealed=seal(content, context=vault_contexts.CONTENT),
            fingerprint=fingerprint(content, context=vault_contexts.CONTENT),
            size=len(content),
            key_names=dotenv.key_names(content),
            source=source,
        )


def _env_path(server: Server) -> str:
    if not server.env_path:
        raise EnvPathMissing()
    return server.env_path


def _opened(version: EnvVersion) -> bytes:
    return unseal(version.content_sealed, context=vault_contexts.CONTENT)


def _read(remote: RemoteHost, path: str) -> bytes:
    try:
        return remote.read_small(path, settings.ENV_MAX_BYTES)
    except FileTooLarge as exc:
        raise EnvTooLarge() from exc


def _regular_file(remote: RemoteHost, path: str) -> RemoteEntry | None:
    try:
        found = remote.lstat(path)
    except RemoteNotFound:
        return None
    if found.kind != FILE:
        raise RemoteNotFound()
    return found
