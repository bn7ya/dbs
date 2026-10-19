from __future__ import annotations

from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.activity.services import ActivityService, sweep_stale_jobs
from dbs.manager.applications.repositories import ApplicationRepository
from dbs.manager.backups.locks import TakeLock


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
    unfinished = {str(entry) for entry in ActivityRepository().unfinished_ids()}
    return len(TakeLock().release_abandoned(applications, unfinished))
