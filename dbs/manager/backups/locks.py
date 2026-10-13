from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from rest_framework.exceptions import APIException

from dbs.manager.backups.exceptions import BackupRunning, ServerSettling
from dbs.manager.servers.settling import settling_until


def _key(server_id: UUID) -> str:
    return f"backups:take:{server_id}"


class TakeLock:
    def acquire(self, server_id: UUID, job_id: UUID) -> bool:
        if settling_until(server_id) is not None:
            return False
        return cache.add(
            _key(server_id), str(job_id), timeout=settings.BACKUP_TASK_TIME_LIMIT
        )

    def hold(self, server_id: UUID, job_id: UUID) -> bool:
        return self.acquire(server_id, job_id) or self.holder(server_id) == str(
            job_id
        )

    def release(self, server_id: UUID, job_id: UUID) -> None:
        if self.holder(server_id) == str(job_id):
            cache.delete(_key(server_id))

    def holder(self, server_id: UUID) -> str | None:
        return cache.get(_key(server_id))

    def refusal(self, server_id: UUID) -> APIException:
        if settling_until(server_id) is not None:
            return ServerSettling()
        return BackupRunning()

    def release_abandoned(
        self, server_ids: Iterable[UUID], unfinished: set[str]
    ) -> list[UUID]:
        released = []
        for server_id in server_ids:
            holder = self.holder(server_id)
            if holder is not None and holder not in unfinished:
                self.release(server_id, holder)
                released.append(server_id)
        return released
