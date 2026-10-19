from __future__ import annotations

from contextlib import suppress

from dbs.manager.applications.services import ApplicationService
from dbs.manager.envfiles.services.env_file_service import EnvFileService


class EnvSnapshotService:
    def __init__(self) -> None:
        self.applications = ApplicationService(None)
        self.envfiles = EnvFileService(None)

    def snapshot_all(self) -> None:
        for application in self.applications.with_env_path():
            with suppress(Exception):
                self.envfiles.snapshot(application)


def snapshot_env_files() -> None:
    EnvSnapshotService().snapshot_all()
