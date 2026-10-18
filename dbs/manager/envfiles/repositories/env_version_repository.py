from __future__ import annotations

from uuid import UUID

from django.db.models import QuerySet

from dbs.manager.common.repositories import BaseRepository
from dbs.manager.envfiles.models import EnvVersion


class EnvVersionRepository(BaseRepository):
    model = EnvVersion

    def active(self) -> QuerySet[EnvVersion]:
        return super().active().select_related("created_by")

    def for_application(self, application_id: UUID) -> QuerySet[EnvVersion]:
        return (
            self.active()
            .filter(application_id=application_id)
            .order_by("-created_at", "-id")
        )

    def newest_for(self, application_id: UUID) -> EnvVersion | None:
        return self.for_application(application_id).first()
