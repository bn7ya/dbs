from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.db.models import QuerySet
from django.utils import timezone
from rest_framework.exceptions import ErrorDetail, NotFound, ValidationError

from dbs import audit
from dbs.manager.activity import heartbeat, job_leases
from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.common.exceptions import error_code_of
from dbs.manager.middleware import current_ip
from dbs.models import AuditEvent, AuditStatus

INVALID_STATUS = "Choose queued, running, succeeded or failed."
STALE_AFTER_LIMIT = timedelta(hours=1)
QUEUED_HERE: ContextVar[list[int] | None] = ContextVar(
    "dbs_manager_queued_here", default=None
)


@contextmanager
def collecting_jobs() -> Iterator[list[int]]:
    queued: list[int] = []
    token = QUEUED_HERE.set(queued)
    try:
        yield queued
    finally:
        QUEUED_HERE.reset(token)


def subject_of(subject: Any) -> str:
    return "" if subject is None else str(subject.pk)


def scope(server: Any = None, application: Any = None) -> list[str] | None:
    from dbs.manager.applications.repositories import ApplicationRepository

    if application is not None:
        return [str(application)]
    if server is None:
        return None
    applications = ApplicationRepository().all_including_deleted().filter(server_id=server)
    return [str(server), *(str(pk) for pk in applications.values_list("pk", flat=True))]


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
        application: Any = None,
        action: str | None = None,
        status: str | None = None,
    ) -> QuerySet:
        if status and status not in AuditStatus.values:
            raise ValidationError(
                {"status": [ErrorDetail(INVALID_STATUS, code="invalid_status")]}
            )
        return self.entries.filtered(
            subjects=scope(server, application), action=action, status=status
        )

    def get(self, activity_id: int) -> AuditEvent:
        entry = self.entries.find_joined(activity_id)
        if entry is None:
            raise NotFound()
        return entry

    def subjects_for(self, entries: Any) -> dict[str, Any]:
        from dbs.manager.applications.repositories import ApplicationRepository
        from dbs.manager.servers.repositories import ServerRepository

        subjects = {entry.subject for entry in entries if entry.subject}
        return {
            **ServerRepository().by_subject(subjects),
            **ApplicationRepository().by_subject(subjects),
        }

    def record(
        self,
        action: str,
        *,
        subject: Any = None,
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
            subject=subject_of(subject),
        )

    @contextmanager
    def track(
        self, action: str, *, subject: Any = None, target: str = ""
    ) -> Iterator[Entry]:
        entry = Entry(
            audit.record(
                action,
                actor=self.user,
                target=target,
                status=audit.RUNNING,
                remote_addr=current_ip() or "",
                subject=subject_of(subject),
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
        subject: Any = None,
        target: str = "",
        detail: dict[str, Any] | None = None,
    ) -> AuditEvent:
        entry = audit.queue(
            action,
            actor=self.user,
            target=target,
            data=detail,
            subject=subject_of(subject),
            remote_addr=current_ip() or "",
        )
        collected = QUEUED_HERE.get()
        if collected is not None:
            collected.append(entry.pk)
        return entry

    def start(self, activity_id: int) -> AuditEvent | None:
        started = audit.start(activity_id)
        if started is not None:
            job_leases.hold(activity_id)
            heartbeat.begin(activity_id)
        return started

    def succeed(self, activity_id: int, detail: dict[str, Any] | None = None) -> None:
        audit.finish(activity_id, data=detail)
        job_leases.let_go(activity_id)
        heartbeat.end(activity_id)

    def fail(
        self,
        activity_id: int,
        error: BaseException,
        detail: dict[str, Any] | None = None,
    ) -> None:
        audit.fail(activity_id, error_code_of(error), data=detail)
        job_leases.let_go(activity_id)
        heartbeat.end(activity_id)

    def progress(self, activity_id: int, detail: dict[str, Any]) -> None:
        self.entries.set_running_data(activity_id, detail)

    def interrupt(
        self, *, idle_since: datetime | None = None, renewed_since: datetime | None = None
    ) -> int:
        if idle_since is None:
            keep = job_leases.live()
        elif renewed_since is not None:
            keep = job_leases.renewed_since(renewed_since)
        else:
            keep = []
        return audit.interrupt(idle_since=idle_since, keep=keep)


def sweep_stale_jobs() -> int:
    limit = timedelta(seconds=settings.BACKUP_TASK_TIME_LIMIT)
    now = timezone.now()
    return ActivityService(None).interrupt(
        idle_since=now - limit - STALE_AFTER_LIMIT, renewed_since=now - STALE_AFTER_LIMIT
    )
