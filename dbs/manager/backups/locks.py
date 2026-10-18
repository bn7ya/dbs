from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from rest_framework.exceptions import APIException

from dbs.manager.backups.exceptions import BackupRunning, ServerSettling
from dbs.manager.servers.settling import settling_until


def _key(application_id: UUID) -> str:
    return f"backups:take:{application_id}"


class TakeLock:
    def acquire(self, application_id: UUID, job_id: UUID) -> bool:
        if settling_until(application_id) is not None:
            return False
        return cache.add(
            _key(application_id), str(job_id), timeout=settings.BACKUP_TASK_TIME_LIMIT
        )

    def hold(self, application_id: UUID, job_id: UUID) -> bool:
        return self.acquire(application_id, job_id) or self.holder(application_id) == str(
            job_id
        )

    def release(self, application_id: UUID, job_id: UUID) -> None:
        if self.holder(application_id) == str(job_id):
            cache.delete(_key(application_id))

    def holder(self, application_id: UUID) -> str | None:
        return cache.get(_key(application_id))

    def refusal(self, application_id: UUID) -> APIException:
        if settling_until(application_id) is not None:
            return ServerSettling()
        return BackupRunning()

    def release_abandoned(
        self, application_ids: Iterable[UUID], unfinished: set[str]
    ) -> list[UUID]:
        released = []
        for application_id in application_ids:
            holder = self.holder(application_id)
            if holder is not None and holder not in unfinished:
                self.release(application_id, holder)
                released.append(application_id)
        return released
