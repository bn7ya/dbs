from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from django.conf import settings
from django.core.cache import cache


def _key(server_id: UUID) -> str:
    return f"relocation:server:{server_id}"


class ServerMoveLock:
    def acquire(self, server_ids: Iterable[UUID], job_id: int) -> bool:
        taken = []
        for server_id in server_ids:
            if not cache.add(
                _key(server_id), str(job_id), timeout=settings.BACKUP_TASK_TIME_LIMIT
            ):
                for held in taken:
                    self.release([held], job_id)
                return False
            taken.append(server_id)
        return True

    def release(self, server_ids: Iterable[UUID], job_id: int) -> None:
        for server_id in server_ids:
            if self.holder(server_id) == str(job_id):
                cache.delete(_key(server_id))

    def holder(self, server_id: UUID) -> str | None:
        return cache.get(_key(server_id))

    def held(self, server_id: UUID) -> bool:
        return self.holder(server_id) is not None

    def release_abandoned(
        self, server_ids: Iterable[UUID], unfinished: set[str]
    ) -> list[UUID]:
        released = []
        for server_id in server_ids:
            holder = self.holder(server_id)
            if holder is not None and holder not in unfinished:
                cache.delete(_key(server_id))
                released.append(server_id)
        return released
