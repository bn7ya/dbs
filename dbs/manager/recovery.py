from __future__ import annotations

import shutil

from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.activity.services import ActivityService, sweep_stale_jobs
from dbs.manager.applications.repositories import ApplicationRepository
from dbs.manager.backups.locks import TakeLock
from dbs.manager.conf import data_dir
from dbs.manager.relocation.locks import ServerMoveLock
from dbs.manager.servers.repositories import ServerRepository

SPOOL_FOLDER = "relocation"


def recover() -> int:
    ActivityService(None).interrupt()
    return release_abandoned_locks()


def sweep() -> int:
    swept = sweep_stale_jobs()
    release_abandoned_locks()
    return swept


def release_abandoned_locks() -> int:
    applications = (
        ApplicationRepository().all_including_deleted().values_list("pk", flat=True)
    )
    servers = ServerRepository().all_including_deleted().values_list("pk", flat=True)
    unfinished = {str(entry) for entry in ActivityRepository().unfinished_ids()}
    released = TakeLock().release_abandoned(applications, unfinished)
    moves = ServerMoveLock().release_abandoned(servers, unfinished)
    sweep_spools(unfinished)
    return len(released) + len(moves)


def sweep_spools(unfinished: set[str]) -> list[str]:
    folder = data_dir() / SPOOL_FOLDER
    if not folder.is_dir():
        return []
    swept = []
    for spool in folder.iterdir():
        if spool.is_dir() and spool.name.isdigit() and spool.name not in unfinished:
            shutil.rmtree(spool, ignore_errors=True)
            swept.append(spool.name)
    return swept
