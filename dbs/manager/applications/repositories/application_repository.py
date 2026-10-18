from __future__ import annotations

from uuid import UUID

from django.db.models import Q, QuerySet

from dbs.manager.applications.models import Application
from dbs.manager.common.repositories import BaseRepository


class ApplicationRepository(BaseRepository):
    model = Application

    def active(self) -> QuerySet[Application]:
        return super().active().select_related("server")

    def search(
        self, query: str | None = None, server_id: UUID | None = None
    ) -> QuerySet[Application]:
        applications = self.active()
        if server_id is not None:
            applications = applications.filter(server_id=server_id)
        if query:
            applications = applications.filter(
                Q(name__icontains=query)
                | Q(server__name__icontains=query)
                | Q(server__host__icontains=query)
            )
        return applications.order_by("name")

    def on_server(self, server_id: UUID) -> QuerySet[Application]:
        return self.active().filter(server_id=server_id).order_by("name")

    def with_env_path(self) -> QuerySet[Application]:
        return self.active().exclude(env_path="").order_by("name")

    def by_subject(self, subjects: set[str]) -> dict[str, Application]:
        ids = []
        for subject in subjects:
            try:
                ids.append(UUID(subject))
            except ValueError:
                continue
        found = self.all_including_deleted().select_related("server").filter(pk__in=ids)
        return {str(application.pk): application for application in found}

    def name_in_use(self, name: str, *, excluding: UUID | None = None) -> bool:
        applications = self.active().filter(name=name)
        if excluding is not None:
            applications = applications.exclude(pk=excluding)
        return applications.exists()
