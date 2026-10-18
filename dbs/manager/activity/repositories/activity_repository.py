from __future__ import annotations

from datetime import datetime

from django.db.models import Count, QuerySet

from dbs.audit import FAILED, RUNNING, SUCCEEDED, UNFINISHED
from dbs.models import AuditEvent


class ActivityRepository:
    def joined(self) -> QuerySet:
        return AuditEvent.objects.select_related("actor")

    def filtered(
        self,
        *,
        subjects: list[str] | None = None,
        action: str | None = None,
        status: str | None = None,
    ) -> QuerySet:
        entries = self.joined()
        if subjects is not None:
            entries = entries.filter(subject__in=subjects)
        if action:
            entries = entries.filter(action=action)
        if status:
            entries = entries.filter(status=status)
        return entries.order_by("-created_at", "-id")

    def find_joined(self, entry_id: int) -> AuditEvent | None:
        return self.joined().filter(pk=entry_id).first()

    def get(self, entry_id: int) -> AuditEvent:
        return self.joined().get(pk=entry_id)

    def unfinished_ids(self) -> set[int]:
        return set(
            AuditEvent.objects.filter(status__in=UNFINISHED).values_list(
                "pk", flat=True
            )
        )

    def set_running_data(self, entry_id: int, data: dict) -> int:
        return AuditEvent.objects.filter(pk=entry_id, status=RUNNING).update(data=data)

    def failures_by_subject(
        self, subjects: list[str], since: datetime
    ) -> dict[str, int]:
        rows = (
            AuditEvent.objects.filter(
                subject__in=subjects, status=FAILED, created_at__gte=since
            )
            .values("subject")
            .annotate(failures=Count("id"))
        )
        return {row["subject"]: row["failures"] for row in rows}

    def recent_failures(self, limit: int) -> list[AuditEvent]:
        return list(
            self.joined().filter(status=FAILED).order_by("-created_at", "-id")[:limit]
        )

    def latest_success(self, action: str) -> AuditEvent | None:
        return (
            AuditEvent.objects.filter(action=action, status=SUCCEEDED)
            .order_by("-created_at", "-id")
            .first()
        )
