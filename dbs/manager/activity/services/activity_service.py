from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.db.models import QuerySet
from django.utils import timezone
from rest_framework.exceptions import ErrorDetail, NotFound, ValidationError

from dbs import audit
from dbs.manager.activity import job_leases
from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.common.exceptions import error_code_of
from dbs.manager.middleware import current_ip
from dbs.manager.servers.repositories import ServerRepository
from dbs.models import AuditEvent, AuditStatus

INVALID_STATUS = "Choose queued, running, succeeded or failed."
STALE_AFTER_LIMIT = timedelta(hours=1)


def subject_of(server: Any) -> str:
    return "" if server is None else str(server.pk)


class Entry:
    def __init__(self, event: AuditEvent) -> None:
        self.pk = event.pk
        self.event = event
        self.detail: dict[str, Any] = {}


class ActivityService:
    def __init__(self, user: Any) -> None:
        self.user = user
        self.entries = ActivityRepository()

    def list(
        self,
        server: Any = None,
        action: str | None = None,
        status: str | None = None,
    ) -> QuerySet:
        if status and status not in AuditStatus.values:
            raise ValidationError(
                {"status": [ErrorDetail(INVALID_STATUS, code="invalid_status")]}
            )
        subject = None if server is None else str(server)
        return self.entries.filtered(subject=subject, action=action, status=status)

    def get(self, activity_id: int) -> AuditEvent:
        entry = self.entries.find_joined(activity_id)
        if entry is None:
            raise NotFound()
        return entry

    def servers_for(self, entries: Any) -> dict[str, Any]:
        return ServerRepository().by_subject(
            {entry.subject for entry in entries if entry.subject}
        )

    def record(
        self,
        action: str,
        *,
        server: Any = None,
        target: str = "",
        detail: dict[str, Any] | None = None,
        status: str = audit.SUCCEEDED,
        error_code: str = "",
    ) -> AuditEvent:
        return audit.record(
            action,
            actor=self.user,
            target=target,
            data=detail,
            status=status,
            error_code=error_code,
            remote_addr=current_ip() or "",
            subject=subject_of(server),
        )

    @contextmanager
    def track(
        self, action: str, *, server: Any = None, target: str = ""
    ) -> Iterator[Entry]:
        entry = Entry(
            audit.record(
                action,
                actor=self.user,
                target=target,
                status=audit.RUNNING,
                remote_addr=current_ip() or "",
                subject=subject_of(server),
            )
        )
        try:
            yield entry
        except BaseException as exc:
            audit.fail(entry.pk, error_code_of(exc), data=entry.detail)
            raise
        audit.finish(entry.pk, data=entry.detail)

    def queue(
        self,
        action: str,
        *,
        server: Any = None,
        target: str = "",
        detail: dict[str, Any] | None = None,
    ) -> AuditEvent:
        return audit.queue(
            action,
            actor=self.user,
            target=target,
            data=detail,
            subject=subject_of(server),
            remote_addr=current_ip() or "",
        )

    def start(self, activity_id: int) -> AuditEvent | None:
        started = audit.start(activity_id)
        if started is not None:
            job_leases.hold(activity_id)
        return started

    def succeed(self, activity_id: int, detail: dict[str, Any] | None = None) -> None:
        audit.finish(activity_id, data=detail)
        job_leases.let_go(activity_id)

    def fail(
        self,
        activity_id: int,
        error: BaseException,
        detail: dict[str, Any] | None = None,
    ) -> None:
        audit.fail(activity_id, error_code_of(error), data=detail)
        job_leases.let_go(activity_id)

    def progress(self, activity_id: int, detail: dict[str, Any]) -> None:
        self.entries.set_running_data(activity_id, detail)

    def interrupt(self, *, idle_since: datetime | None = None) -> int:
        keep = job_leases.live() if idle_since is None else []
        return audit.interrupt(idle_since=idle_since, keep=keep)


def sweep_stale_jobs() -> int:
    limit = timedelta(seconds=settings.BACKUP_TASK_TIME_LIMIT)
    return ActivityService(None).interrupt(
        idle_since=timezone.now() - limit - STALE_AFTER_LIMIT
    )
