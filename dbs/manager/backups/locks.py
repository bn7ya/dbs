from __future__ import annotations

from uuid import UUID

from django.conf import settings
from django.core.cache import cache


def _key(server_id: UUID) -> str:
    return f"backups:take:{server_id}"


class TakeLock:
    def acquire(self, server_id: UUID, job_id: UUID) -> bool:
        return cache.add(
            _key(server_id), str(job_id), timeout=settings.BACKUP_TASK_TIME_LIMIT
        )

    def hold(self, server_id: UUID, job_id: UUID) -> bool:
        return self.acquire(server_id, job_id) or cache.get(_key(server_id)) == str(
            job_id
        )

    def release(self, server_id: UUID, job_id: UUID) -> None:
        if cache.get(_key(server_id)) == str(job_id):
            cache.delete(_key(server_id))
