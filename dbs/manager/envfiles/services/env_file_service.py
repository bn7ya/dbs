from __future__ import annotations

import posixpath
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast
from uuid import UUID

from django.conf import settings
from django.db.models import QuerySet
from django.views.decorators.debug import sensitive_variables
from rest_framework.exceptions import NotFound

from dbs.manager.accounts.services import AccountService
from dbs.manager.activity.services import ActivityService
from dbs.manager.applications.models import Application
from dbs.manager.applications.paths import host_path
from dbs.manager.applications.services import ApplicationService
from dbs.manager.envfiles import dotenv
from dbs.manager.envfiles.exceptions import (
    DifferentApplications,
    EnvFolderShared,
    EnvPathMissing,
    EnvTooLarge,
)
from dbs.manager.envfiles.models import EnvVersion
from dbs.manager.envfiles.repositories import EnvVersionRepository
from dbs.manager.envfiles.services import vault_contexts
from dbs.manager.servers.exceptions import FileTooLarge, RemoteNotFound
from dbs.manager.servers.services import ServerConnectionService, pythons
from dbs.manager.vault import fingerprint, seal, unseal
from dbs.manager.permissions import Capability, requires

if TYPE_CHECKING:
    from django.contrib.auth.models import AnonymousUser, User

    from dbs.manager.servers.gateways import DbsProfile, RemoteEntry, RemoteHost

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
        self.applications = ApplicationService(user)
        self.connections = ServerConnectionService(user)
        self.activity = ActivityService(user)

    def list(self, application_id: UUID) -> QuerySet[EnvVersion]:
        return self.versions.for_application(application_id)

    def get(self, version_id: UUID) -> EnvVersion:
        version = self.versions.find(version_id)
        if version is None:
            raise NotFound()
        return version

    @sensitive_variables()
    def compare(self, version_id: UUID, other_id: UUID) -> Comparison:
        source, target = self.get(version_id), self.get(other_id)
        if source.application_id != target.application_id:
            raise DifferentApplications()
        found = dotenv.diff(_opened(source), _opened(target))
        return Comparison(
            from_id=source.pk,
            to_id=target.pk,
            added=found.added,
            removed=found.removed,
            changed=found.changed,
        )

    @requires(Capability.ENV_PULL)
    def pull(self, application_id: UUID) -> Pulled:
        return self._pull(
            self.applications.get(application_id), EnvVersion.Source.PULLED
        )

    def snapshot(self, application: Application) -> Pulled:
        return self._pull(application, EnvVersion.Source.SCHEDULED)

    @sensitive_variables()
    @requires(Capability.ENV_REVEAL)
    def reveal(self, version_id: UUID, password: str) -> str:
        version = self.get(version_id)
        with self.activity.track(
            Action.REVEAL, subject=version.application, target=version.path
        ) as entry:
            entry.detail = {"version": str(version.pk)}
            AccountService(self.user).confirm_password(password)
            content = _opened(version)
        return content.decode("utf-8", errors="replace")

    @sensitive_variables()
    @requires(Capability.ENV_PUSH)
    def push(self, version_id: UUID, password: str) -> EnvVersion:
        version = self.get(version_id)
        application = self.applications.get(version.application_id)
        with self.activity.track(
            Action.PUSH, subject=application, target=application.env_path
        ) as entry:
            entry.detail = {"from_version": str(version.pk)}
            AccountService(self.user).confirm_password(password)
            return self._write(version, application)

    @sensitive_variables()
    def copy_to(self, version_id: UUID, application: Application) -> EnvVersion:
        version = self.get(version_id)
        with self.activity.track(
            Action.PUSH, subject=application, target=application.env_path
        ) as entry:
            entry.detail = {"from_version": str(version.pk)}
            return self._write(version, application)

    @sensitive_variables()
    def _write(self, version: EnvVersion, application: Application) -> EnvVersion:
        path = _env_path(application)
        content = _opened(version)
        with self.connections.open(application) as remote:
            inside = _inside_container(application, path)
            if inside:
                profile = self.connections.dbs_profile(application)
                current = _read_in_container(remote, profile, path, missing_ok=True)
                if current is not None:
                    self._keep(application, path, current, EnvVersion.Source.PULLED)
                remote.replace_in_container(profile, path, content)
            else:
                self._replace_on_host(application, remote, path, content)
        return self._store(application, path, content, EnvVersion.Source.PUSHED)

    @sensitive_variables()
    def _replace_on_host(
        self, application: Application, remote: RemoteHost, path: str, content: bytes
    ) -> None:
        real = _trusted_place(remote, _on_host(application, path))
        current = _regular_file(remote, real)
        mode, owner = NEW_FILE_MODE, None
        if current is not None:
            self._keep(application, path, _read(remote, real), EnvVersion.Source.PULLED)
            mode = NEW_FILE_MODE if current.permissions is None else current.permissions
            if current.uid is not None and current.gid is not None:
                owner = (current.uid, current.gid)
        remote.replace_file(real, content, mode=mode, owner=owner)

    @sensitive_variables()
    def _pull(self, application: Application, source: str) -> Pulled:
        with self.activity.track(
            Action.PULL, subject=application, target=application.env_path
        ) as entry:
            path = _env_path(application)
            with self.connections.open(application) as remote:
                if _inside_container(application, path):
                    content = cast(
                        bytes,
                        _read_in_container(
                            remote, self.connections.dbs_profile(application), path
                        ),
                    )
                else:
                    content = _read(
                        remote, _trusted_place(remote, _on_host(application, path))
                    )
            pulled = self._keep(application, path, content, source)
            entry.detail = {"created": pulled.created}
        return pulled

    @sensitive_variables()
    def _keep(
        self, application: Application, path: str, content: bytes, source: str
    ) -> Pulled:
        newest = self.versions.newest_for(application.pk)
        made = fingerprint(content, context=vault_contexts.CONTENT)
        if newest is not None and newest.path == path and newest.fingerprint == made:
            return Pulled(created=False, version=newest)
        return Pulled(
            created=True, version=self._store(application, path, content, source)
        )

    @sensitive_variables()
    def _store(
        self, application: Application, path: str, content: bytes, source: str
    ) -> EnvVersion:
        return self.versions.create(
            created_by=cast("User | None", self.user),
            application=application,
            path=path,
            content_sealed=seal(content, context=vault_contexts.CONTENT),
            fingerprint=fingerprint(content, context=vault_contexts.CONTENT),
            size=len(content),
            key_names=dotenv.key_names(content),
            source=source,
        )


def _env_path(application: Application) -> str:
    if not application.env_path:
        raise EnvPathMissing()
    return application.env_path


def _inside_container(application: Application, path: str) -> bool:
    return application.env_in_container and host_path(application, path) is None


def _on_host(application: Application, path: str) -> str:
    if application.env_in_container:
        return host_path(application, path) or path
    return path


def _read_in_container(
    remote: RemoteHost, profile: DbsProfile, path: str, *, missing_ok: bool = False
) -> bytes | None:
    try:
        return remote.read_in_container(profile, path, settings.ENV_MAX_BYTES)
    except FileTooLarge as exc:
        raise EnvTooLarge() from exc
    except RemoteNotFound:
        if missing_ok:
            return None
        raise


def _opened(version: EnvVersion) -> bytes:
    return unseal(version.content_sealed, context=vault_contexts.CONTENT)


def _trusted_place(remote: RemoteHost, path: str) -> str:
    real = remote.realpath(path)
    for folder in dict.fromkeys((posixpath.dirname(path), posixpath.dirname(real))):
        if not pythons.trusted_with_parent(remote, folder):
            raise EnvFolderShared()
    return real


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
