from __future__ import annotations

from datetime import datetime
from uuid import UUID

from django.db.models import QuerySet

from dbs.manager.backups.models import BackupPlan
from dbs.manager.common.repositories import BaseRepository


class BackupPlanRepository(BaseRepository):
    model = BackupPlan

    def alive_for_server(self, server_id: UUID) -> QuerySet[BackupPlan]:
        return self.active().filter(server_id=server_id).order_by("name", "id")

    def name_in_use(
        self, server_id: UUID, name: str, *, excluding: UUID | None = None
    ) -> bool:
        plans = self.active().filter(server_id=server_id, name=name)
        if excluding is not None:
            plans = plans.exclude(pk=excluding)
        return plans.exists()

    def lock_scheduled_by(self, moment: datetime) -> QuerySet[BackupPlan]:
        return (
            self.active()
            .filter(
                enabled=True,
                interval_minutes__isnull=False,
                next_run_at__lte=moment,
                server__deleted_at__isnull=True,
            )
            .select_related("server")
            .select_for_update(skip_locked=True, of=("self",))
            .order_by("next_run_at", "id")
        )
