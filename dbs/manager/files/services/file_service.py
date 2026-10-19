from __future__ import annotations

import posixpath
from collections.abc import Iterator, Sequence
from contextlib import ExitStack
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from rest_framework.exceptions import ErrorDetail, ValidationError

from dbs import audit
from dbs.manager.accounts.exceptions import InvalidPassword, TooManyAttempts
from dbs.manager.accounts.services import AccountService
from dbs.manager.activity.services import ActivityService
from dbs.manager.applications.models import Application
from dbs.manager.applications.paths import host_path
from dbs.manager.applications.services import ApplicationService
from dbs.manager.common import tickets
from dbs.manager.common.exceptions import error_code_of
from dbs.manager.common.paths import absolute_path
from dbs.manager.common.uploads import UploadTooLarge, upload_name, utf8_length
from dbs.manager.files import paths
from dbs.manager.files.exceptions import CannotDeleteRoot, NotAFile
from dbs.manager.files.paths import Located
from dbs.manager.servers.exceptions import (
    RemoteCommandFailed,
    RemoteNotFound,
    RemotePermissionDenied,
)
from dbs.manager.servers.services import ServerConnectionService
from dbs.manager.permissions import Capability, requires
from dbs.models import AuditEvent

if TYPE_CHECKING:
    from django.contrib.auth.models import AnonymousUser, User

    from dbs.manager.servers.gateways import RemoteEntry, RemoteHost

FILE = "file"
FOLDER = "folder"

INVALID_NAME = "Give it a name without / or \\, not . or .., and not only spaces."
TARGET_MAX_LENGTH: int = cast(int, AuditEvent._meta.get_field("target_name").max_length)
DOWNLOAD_NAME = "download"
ENV_NAME = ".env"
ENV_PASSWORD_REQUIRED = "Enter your own password to download a .env file."


class Action:
    DOWNLOAD = "files.download"
    UPLOAD = "files.upload"
    CREATE_FOLDER = "files.create_folder"
    DELETE = "files.delete"


@dataclass(frozen=True)
class Folder:
    path: str
    parent: str | None
    root: str
    roots: list[str]
    entries: list[Any]


class RemoteContent:
    def __init__(self, chunks: Iterator[bytes], stack: ExitStack) -> None:
        self.chunks = chunks
        self.stack = stack

    def __iter__(self) -> Iterator[bytes]:
        return self.chunks

    def close(self) -> None:
        self.stack.close()


@dataclass(frozen=True)
class Download:
    content: RemoteContent
    name: str
    size: int | None


class _Guard:
    def __init__(self, remote: RemoteHost, roots: Sequence[str]) -> None:
        self.remote: RemoteHost = remote
        self.real_roots: list[str] = [
            real for real in map(self._real_root, roots) if real is not None
        ]

    def followed(self, path: str) -> str:
        return paths.resolved(self.remote.realpath(path), self.real_roots)

    def itself(self, located: Located) -> str:
        return posixpath.join(
            self.followed(posixpath.dirname(located.path)), located.name
        )

    def _real_root(self, root: str) -> str | None:
        try:
            return absolute_path(self.remote.realpath(root))
        except (RemoteNotFound, RemotePermissionDenied):
            return None


class FileService:
    def __init__(self, user: User | AnonymousUser | None) -> None:
        self.user: User | AnonymousUser | None = user
        self.applications = ApplicationService(user)
        self.connections = ServerConnectionService(user)
        self.activity = ActivityService(user)

    def list(self, application_id: UUID, path: str | None = None) -> Folder:
        application = self.applications.get(application_id)
        roots = paths.allowed_roots(_host_roots(application))
        located = paths.locate(path or next(iter(roots), ""), roots)
        with self.connections.open(application) as remote:
            entries = remote.listdir(_Guard(remote, roots).followed(located.path))
        shown = [
            replace(entry, path=posixpath.join(located.path, entry.name))
            for entry in entries
        ]
        return Folder(
            path=located.path,
            parent=located.parent,
            root=located.root,
            roots=roots,
            entries=sorted(shown, key=_listing_order),
        )

    @requires(Capability.FILES_DOWNLOAD)
    def download(
        self,
        application_id: UUID,
        path: str,
        account_password: str = "",
        ticket: str = "",
    ) -> Download:
        application = self.applications.get(application_id)
        if _names_env(application, posixpath.normpath(path)) and not (
            account_password or ticket
        ):
            _require_password()
        with ExitStack() as stack:
            with self.activity.track(
                Action.DOWNLOAD, subject=application, target=_shown(path)
            ) as entry:
                roots = paths.allowed_roots(_host_roots(application))
                located = paths.locate(path, roots)
                remote = stack.enter_context(self.connections.open(application))
                real = _Guard(remote, roots).followed(located.path)
                found = remote.lstat(real)
                if found.kind != FILE:
                    raise NotAFile()
                if _holds_env(application, remote, located.path, real):
                    subject = _download_subject(application, located.path)
                    if not (ticket and tickets.redeem(ticket, self.user, subject)):
                        _require_password(account_password)
                        AccountService(self.user).confirm_password(account_password)
                chunks = stack.enter_context(remote.stream_file(real, found.size))
                entry.detail = {"size": found.size}
            content = RemoteContent(chunks, stack.pop_all())
        return Download(
            content=content, name=_download_name(located.name), size=found.size
        )

    @requires(Capability.FILES_DOWNLOAD)
    def download_ticket(
        self, application_id: UUID, path: str, account_password: str = ""
    ) -> str:
        application = self.applications.get(application_id)
        located = paths.locate(path, paths.allowed_roots(_host_roots(application)))
        if not account_password:
            if _names_env(application, located.path):
                _require_password()
            return ""
        try:
            AccountService(self.user).confirm_password(account_password)
        except (InvalidPassword, TooManyAttempts) as exc:
            self.activity.record(
                Action.DOWNLOAD,
                subject=application,
                target=_shown(located.path),
                status=audit.FAILED,
                error_code=error_code_of(exc),
            )
            raise
        return tickets.issue(self.user, _download_subject(application, located.path))

    @requires(Capability.FILES_CHANGE)
    def upload(self, application_id: UUID, folder: str, upload: UploadedFile) -> RemoteEntry:
        try:
            name = upload_name(upload.name or "", paths.NAME_MAX_BYTES, utf8_length)
            if name is None:
                raise ValidationError(
                    {"file": [ErrorDetail(INVALID_NAME, code="invalid_name")]}
                )
            if cast(int, upload.size) > settings.FILES_UPLOAD_MAX_BYTES:
                raise UploadTooLarge()
            application = self.applications.get(application_id)
            target = _shown(posixpath.join(folder, name))
            with self.activity.track(
                Action.UPLOAD, subject=application, target=target
            ) as entry:
                roots = paths.allowed_roots(_host_roots(application))
                located = paths.locate(folder, roots)
                with self.connections.open(application) as remote:
                    real = _Guard(remote, roots).followed(located.path)
                    created = remote.write_new(upload, real, name)
                entry.detail = {"size": created.size}
        finally:
            upload.close()
        return replace(created, path=posixpath.join(located.path, name))

    @requires(Capability.FILES_CHANGE)
    def create_folder(self, application_id: UUID, folder: str, name: str) -> RemoteEntry:
        if paths.entry_name(name) is None:
            raise ValidationError(
                {"name": [ErrorDetail(INVALID_NAME, code="invalid_name")]}
            )
        application = self.applications.get(application_id)
        target = _shown(posixpath.join(folder, name))
        with self.activity.track(Action.CREATE_FOLDER, subject=application, target=target):
            roots = paths.allowed_roots(_host_roots(application))
            located = paths.locate(folder, roots)
            with self.connections.open(application) as remote:
                real = _Guard(remote, roots).followed(located.path)
                created = remote.make_folder(posixpath.join(real, name))
        return replace(created, path=posixpath.join(located.path, name))

    @requires(Capability.FILES_CHANGE)
    def delete(self, application_id: UUID, path: str) -> None:
        application = self.applications.get(application_id)
        with self.activity.track(
            Action.DELETE, subject=application, target=_shown(path)
        ) as entry:
            roots = paths.allowed_roots(_host_roots(application))
            located = paths.locate(path, roots)
            if located.path in roots:
                raise CannotDeleteRoot()
            with self.connections.open(application) as remote:
                guard = _Guard(remote, roots)
                itself = guard.itself(located)
                if itself in guard.real_roots:
                    raise CannotDeleteRoot()
                found = remote.lstat(itself)
                if found.kind == FOLDER:
                    remote.remove_empty_folder(itself)
                else:
                    remote.remove_file(itself)
            entry.detail = {"kind": str(found.kind)}


def _host_roots(application: Application) -> list[str]:
    found = (host_path(application, root) for root in application.file_roots)
    return [root for root in found if root is not None]


def _env_on_host(application: Application) -> str:
    if not application.env_path:
        return ""
    return host_path(application, application.env_path) or ""


def _names_env(application: Application, path: str) -> bool:
    name = posixpath.basename(path)
    env = _env_on_host(application)
    return (
        name == ENV_NAME
        or name.startswith(f"{ENV_NAME}.")
        or (bool(env) and path == env)
    )


def _holds_env(
    application: Application, remote: RemoteHost, path: str, real: str
) -> bool:
    if _names_env(application, path) or _names_env(application, real):
        return True
    env = _env_on_host(application)
    if not env:
        return False
    try:
        return remote.realpath(env) == real
    except (RemoteNotFound, RemotePermissionDenied, RemoteCommandFailed):
        return False


def _require_password(account_password: str = "") -> None:
    if not account_password:
        raise ValidationError(
            {"account_password": [ErrorDetail(ENV_PASSWORD_REQUIRED, code="required")]}
        )


def _download_subject(application: Application, path: str) -> str:
    return f"files:{application.pk}:{path}"


def _listing_order(entry: RemoteEntry) -> tuple[bool, str, str]:
    return (entry.kind != FOLDER, entry.name.casefold(), entry.name)


def _shown(path: str) -> str:
    printable = "".join(character for character in path if character.isprintable())
    if len(printable) <= TARGET_MAX_LENGTH:
        return printable
    return "…" + printable[-(TARGET_MAX_LENGTH - 1) :]


def _download_name(name: str) -> str:
    return (
        "".join(character for character in name if character.isprintable())
        or DOWNLOAD_NAME
    )
