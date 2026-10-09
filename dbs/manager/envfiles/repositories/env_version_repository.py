from __future__ import annotations

from uuid import UUID

from django.db.models import QuerySet

from dbs.manager.common.repositories import BaseRepository
from dbs.manager.envfiles.models import EnvVersion


class EnvVersionRepository(BaseRepository):
    model = EnvVersion

    def active(self) -> QuerySet[EnvVersion]:
        return super().active().select_related("created_by")

    def for_server(self, server_id: UUID) -> QuerySet[EnvVersion]:
        return self.active().filter(server_id=server_id).order_by("-created_at", "-id")

    def newest_for(self, server_id: UUID) -> EnvVersion | None:
        return self.for_server(server_id).first()
