from __future__ import annotations

from contextlib import suppress

from dbs.manager.envfiles.services.env_file_service import EnvFileService
from dbs.manager.servers.services import ServerService


class EnvSnapshotService:
    def __init__(self) -> None:
        self.servers = ServerService(None)
        self.envfiles = EnvFileService(None)

    def snapshot_all(self) -> None:
        for server in self.servers.with_env_path():
            with suppress(Exception):
                self.envfiles.snapshot(server)


def snapshot_env_files() -> None:
    EnvSnapshotService().snapshot_all()
