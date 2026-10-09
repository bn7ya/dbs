from __future__ import annotations

from django.db.models import QuerySet

from dbs.models import AuditEvent


class ActivityRepository:
    def joined(self) -> QuerySet:
        return AuditEvent.objects.select_related("actor")

    def filtered(
        self,
        *,
        subject: str | None = None,
        action: str | None = None,
        status: str | None = None,
    ) -> QuerySet:
        entries = self.joined()
        if subject is not None:
            entries = entries.filter(subject=subject)
        if action:
            entries = entries.filter(action=action)
        if status:
            entries = entries.filter(status=status)
        return entries.order_by("-created_at", "-id")

    def find_joined(self, entry_id: int) -> AuditEvent | None:
        return self.joined().filter(pk=entry_id).first()

    def get(self, entry_id: int) -> AuditEvent:
        return self.joined().get(pk=entry_id)
