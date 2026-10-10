from __future__ import annotations

import posixpath
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any
from uuid import UUID

from dbs.manager.servers.gateways import EntryKind
from dbs.manager.servers.services.connection_service import ServerConnectionService
from dbs.manager.servers.services.server_service import ServerService

if TYPE_CHECKING:
    from dbs.manager.servers.gateways import RemoteEntry

MANAGE = "manage.py"
BROWSE_LIMIT = 5000


@dataclass(frozen=True)
class RemoteFolder:
    path: str
    parent: str | None
    home: str
    project: bool
    truncated: bool
    entries: list[Any]


class BrowseService:
    def __init__(self, user: Any) -> None:
        self.servers = ServerService(user)
        self.connections = ServerConnectionService(user)

    def list(self, server_id: UUID, path: str | None = None) -> RemoteFolder:
        server = self.servers.get(server_id)
        with self.connections.open(server) as remote:
            home = remote.realpath(".")
            folder = path or home
            entries, truncated = remote.listdir_limited(folder, BROWSE_LIMIT)
        shown = [
            replace(entry, path=posixpath.join(folder, entry.name)) for entry in entries
        ]
        return RemoteFolder(
            path=folder,
            parent=None if folder == "/" else posixpath.dirname(folder),
            home=home,
            project=any(
                entry.name == MANAGE and entry.kind == EntryKind.FILE
                for entry in entries
            ),
            truncated=truncated,
            entries=sorted(shown, key=_listing_order),
        )


def _listing_order(entry: RemoteEntry) -> tuple[bool, str, str]:
    return (entry.kind != EntryKind.FOLDER, entry.name.casefold(), entry.name)
