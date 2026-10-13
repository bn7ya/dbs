from __future__ import annotations

from datetime import datetime
from uuid import UUID

from django.db.models import Q, QuerySet

from dbs.manager.common.repositories import BaseRepository
from dbs.manager.servers.models import Server


class ServerRepository(BaseRepository):
    model = Server

    def search(self, query: str | None = None) -> QuerySet[Server]:
        servers = self.active()
        if query:
            servers = servers.filter(
                Q(name__icontains=query) | Q(host__icontains=query)
            )
        return servers.order_by("name")

    def with_env_path(self) -> QuerySet[Server]:
        return self.active().exclude(env_path="").order_by("name")

    def by_subject(self, subjects: set[str]) -> dict[str, Server]:
        ids = []
        for subject in subjects:
            try:
                ids.append(UUID(subject))
            except ValueError:
                continue
        found = self.all_including_deleted().filter(pk__in=ids)
        return {str(server.pk): server for server in found}

    def record_connection(
        self,
        server: Server,
        *,
        state: str,
        error: str,
        seen_at: datetime | None = None,
    ) -> None:
        fields: dict[str, object] = {
            "connection_state": state,
            "last_connection_error": error,
        }
        if seen_at is not None:
            fields["last_seen_at"] = seen_at
        self.all_including_deleted().filter(pk=server.pk).update(**fields)
        for name, value in fields.items():
            setattr(server, name, value)

    def name_in_use(self, name: str, *, excluding: UUID | None = None) -> bool:
        servers = self.active().filter(name=name)
        if excluding is not None:
            servers = servers.exclude(pk=excluding)
        return servers.exists()
