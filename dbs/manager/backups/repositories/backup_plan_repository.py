from __future__ import annotations

from datetime import datetime
from uuid import UUID

from django.db.models import Min, QuerySet

from dbs.manager.backups.models import PLAN_KEEP_MAX, PLAN_KEEP_MIN, BackupPlan
from dbs.manager.common.repositories import BaseRepository


class BackupPlanRepository(BaseRepository):
    model = BackupPlan

    def alive_for_application(self, application_id: UUID) -> QuerySet[BackupPlan]:
        return self.active().filter(application_id=application_id).order_by("name", "id")

    def name_in_use(
        self, application_id: UUID, name: str, *, excluding: UUID | None = None
    ) -> bool:
        plans = self.active().filter(application_id=application_id, name=name)
        if excluding is not None:
            plans = plans.exclude(pk=excluding)
        return plans.exists()

    def names_for_application(
        self, application_id: UUID, *, excluding: UUID | None = None
    ) -> QuerySet[BackupPlan, str]:
        plans = self.active().filter(application_id=application_id)
        if excluding is not None:
            plans = plans.exclude(pk=excluding)
        return plans.values_list("name", flat=True)

    def keep_within_limits(self) -> None:
        plans = self.all_including_deleted()
        plans.filter(keep__gt=PLAN_KEEP_MAX).update(keep=PLAN_KEEP_MAX)
        plans.filter(keep__lt=PLAN_KEEP_MIN).update(keep=PLAN_KEEP_MIN)
        plans.filter(keep_remote__gt=PLAN_KEEP_MAX).update(keep_remote=PLAN_KEEP_MAX)

    def lock_scheduled_by(self, moment: datetime) -> QuerySet[BackupPlan]:
        return (
            self.active()
            .filter(
                enabled=True,
                interval_minutes__isnull=False,
                next_run_at__lte=moment,
                application__deleted_at__isnull=True,
            )
            .select_related("application__server")
            .select_for_update(skip_locked=True, of=("self",))
            .order_by("next_run_at", "id")
        )

    def next_runs_by_application(self) -> dict[UUID, datetime]:
        rows = (
            self.active()
            .filter(
                enabled=True, interval_minutes__isnull=False, next_run_at__isnull=False
            )
            .values("application_id")
            .annotate(following=Min("next_run_at"))
        )
        return {row["application_id"]: row["following"] for row in rows}
