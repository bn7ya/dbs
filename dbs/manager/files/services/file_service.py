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

from dbs.manager.activity.services import ActivityService
from dbs.manager.common.paths import absolute_path
from dbs.manager.common.uploads import UploadTooLarge, upload_name, utf8_length
from dbs.manager.files import paths
from dbs.manager.files.exceptions import CannotDeleteRoot, NotAFile
from dbs.manager.files.paths import Located
from dbs.manager.servers.exceptions import RemoteNotFound, RemotePermissionDenied
from dbs.manager.servers.services import ServerConnectionService, ServerService
from dbs.models import AuditEvent

if TYPE_CHECKING:
    from django.contrib.auth.models import AnonymousUser, User

    from dbs.manager.servers.gateways import RemoteEntry, RemoteHost

FILE = "file"
FOLDER = "folder"

INVALID_NAME = "Give it a name without / or \\, not . or .., and not only spaces."
TARGET_MAX_LENGTH: int = cast(int, AuditEvent._meta.get_field("target_name").max_length)
DOWNLOAD_NAME = "download"


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
        self.servers = ServerService(user)
        self.connections = ServerConnectionService(user)
        self.activity = ActivityService(user)

    def list(self, server_id: UUID, path: str | None = None) -> Folder:
        server = self.servers.get(server_id)
        roots = paths.allowed_roots(server.file_roots)
        located = paths.locate(path or next(iter(roots), ""), roots)
        with self.connections.open(server) as remote:
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

    def download(self, server_id: UUID, path: str) -> Download:
        server = self.servers.get(server_id)
        with ExitStack() as stack:
            with self.activity.track(
                Action.DOWNLOAD, server=server, target=_shown(path)
            ) as entry:
                roots = paths.allowed_roots(server.file_roots)
                located = paths.locate(path, roots)
                remote = stack.enter_context(self.connections.open(server))
                real = _Guard(remote, roots).followed(located.path)
                found = remote.lstat(real)
                if found.kind != FILE:
                    raise NotAFile()
                chunks = stack.enter_context(remote.stream_file(real, found.size))
                entry.detail = {"size": found.size}
            content = RemoteContent(chunks, stack.pop_all())
        return Download(
            content=content, name=_download_name(located.name), size=found.size
        )

    def upload(self, server_id: UUID, folder: str, upload: UploadedFile) -> RemoteEntry:
        try:
            name = upload_name(upload.name or "", paths.NAME_MAX_BYTES, utf8_length)
            if name is None:
                raise ValidationError(
                    {"file": [ErrorDetail(INVALID_NAME, code="invalid_name")]}
                )
            if cast(int, upload.size) > settings.FILES_UPLOAD_MAX_BYTES:
                raise UploadTooLarge()
            server = self.servers.get(server_id)
            target = _shown(posixpath.join(folder, name))
            with self.activity.track(
                Action.UPLOAD, server=server, target=target
            ) as entry:
                roots = paths.allowed_roots(server.file_roots)
                located = paths.locate(folder, roots)
                with self.connections.open(server) as remote:
                    real = _Guard(remote, roots).followed(located.path)
                    created = remote.write_new(upload, real, name)
                entry.detail = {"size": created.size}
        finally:
            upload.close()
        return replace(created, path=posixpath.join(located.path, name))

    def create_folder(self, server_id: UUID, folder: str, name: str) -> RemoteEntry:
        if paths.entry_name(name) is None:
            raise ValidationError(
                {"name": [ErrorDetail(INVALID_NAME, code="invalid_name")]}
            )
        server = self.servers.get(server_id)
        target = _shown(posixpath.join(folder, name))
        with self.activity.track(Action.CREATE_FOLDER, server=server, target=target):
            roots = paths.allowed_roots(server.file_roots)
            located = paths.locate(folder, roots)
            with self.connections.open(server) as remote:
                real = _Guard(remote, roots).followed(located.path)
                created = remote.make_folder(posixpath.join(real, name))
        return replace(created, path=posixpath.join(located.path, name))

    def delete(self, server_id: UUID, path: str) -> None:
        server = self.servers.get(server_id)
        with self.activity.track(
            Action.DELETE, server=server, target=_shown(path)
        ) as entry:
            roots = paths.allowed_roots(server.file_roots)
            located = paths.locate(path, roots)
            if located.path in roots:
                raise CannotDeleteRoot()
            with self.connections.open(server) as remote:
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
