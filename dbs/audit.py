from __future__ import annotations

import logging
import os
from contextlib import contextmanager

from django.db import DatabaseError, transaction
from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger("dbs.audit")

QUEUED = "queued"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
FINISHED = (SUCCEEDED, FAILED)
UNFINISHED = (QUEUED, RUNNING)
INTERRUPTED = "interrupted"

ACTION_MAX = 64
TARGET_MAX = 1024
DETAIL_MAX = 4000
ADDRESS_MAX = 64
ERROR_CODE_MAX = 64
SUBJECT_MAX = 64


def _known_actor(actor):
    if actor is None or not getattr(actor, "is_authenticated", False):
        return None
    return actor if getattr(actor, "pk", None) else None


def record(
    action,
    *,
    actor=None,
    target="",
    detail="",
    data=None,
    status=SUCCEEDED,
    error_code="",
    remote_addr="",
    subject="",
    started_at=None,
    finished_at=None,
):
    from .models import AuditEvent

    now = timezone.now()
    if finished_at is None and status in FINISHED:
        finished_at = now
    return AuditEvent.objects.create(
        actor=_known_actor(actor),
        action=str(action)[:ACTION_MAX],
        target_name=str(target or "")[:TARGET_MAX],
        detail=str(detail or "")[:DETAIL_MAX],
        data=dict(data or {}),
        status=status,
        succeeded=status == SUCCEEDED,
        error_code=str(error_code or "")[:ERROR_CODE_MAX],
        remote_addr=str(remote_addr or "")[:ADDRESS_MAX],
        subject=str(subject or "")[:SUBJECT_MAX],
        started_at=started_at or now,
        finished_at=finished_at,
    )


def safe_record(action, **fields):
    try:
        with transaction.atomic():
            return record(action, **fields)
    except DatabaseError as exc:
        logger.warning("Could not write the %s audit entry: %s", action, exc)
        return None


def error_code_for(exc):
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code:
        return code
    return type(exc).__name__


class Tracked:
    def __init__(self, target, data):
        self.target = target
        self.data = data


@contextmanager
def track(action, *, target="", data=None, **fields):
    started_at = timezone.now()
    entry = Tracked(target, dict(data or {}))
    try:
        yield entry
    except BaseException as exc:
        safe_record(
            action,
            target=entry.target,
            data=entry.data,
            detail=str(exc),
            status=FAILED,
            error_code=error_code_for(exc),
            started_at=started_at,
            **fields,
        )
        raise
    safe_record(
        action, target=entry.target, data=entry.data, started_at=started_at, **fields
    )


def record_backup(output, container, digest, database):
    from .models import BackupRecord

    try:
        with transaction.atomic():
            return BackupRecord.objects.create(
                filename=os.path.basename(output),
                size_bytes=len(container),
                sha256=digest,
                database=database,
                location=os.path.abspath(output),
            )
    except DatabaseError as exc:
        logger.warning("Could not record the backup %s: %s", output, exc)
        return None


def queue(action, *, actor=None, target="", data=None, subject="", remote_addr=""):
    from .models import AuditEvent

    return AuditEvent.objects.create(
        actor=_known_actor(actor),
        action=str(action)[:ACTION_MAX],
        target_name=str(target or "")[:TARGET_MAX],
        data=dict(data or {}),
        status=QUEUED,
        succeeded=False,
        remote_addr=str(remote_addr or "")[:ADDRESS_MAX],
        subject=str(subject or "")[:SUBJECT_MAX],
    )


def start(event_id):
    from .models import AuditEvent

    started = AuditEvent.objects.filter(pk=event_id, status__in=UNFINISHED).update(
        status=RUNNING, started_at=timezone.now()
    )
    if not started:
        return None
    return AuditEvent.objects.select_related("actor").get(pk=event_id)


def finish(event_id, *, data=None):
    return _close(event_id, SUCCEEDED, data=data)


def fail(event_id, error_code, *, data=None, detail=""):
    return _close(event_id, FAILED, data=data, error_code=error_code, detail=detail)


def _close(event_id, status, *, data=None, error_code="", detail=""):
    from .models import AuditEvent

    fields = {
        "status": status,
        "succeeded": status == SUCCEEDED,
        "error_code": str(error_code or "")[:ERROR_CODE_MAX],
        "finished_at": timezone.now(),
    }
    if data is not None:
        fields["data"] = dict(data)
    if detail:
        fields["detail"] = str(detail)[:DETAIL_MAX]
    return AuditEvent.objects.filter(pk=event_id, status__in=UNFINISHED).update(**fields)


def interrupt(*, idle_since=None, keep=()):
    from .models import AuditEvent

    queued = Q(status=QUEUED)
    running = Q(status=RUNNING)
    if idle_since is not None:
        queued &= Q(created_at__lt=idle_since)
        running &= Q(started_at__lt=idle_since)
    return AuditEvent.objects.filter(queued | running).exclude(pk__in=keep).update(
        status=FAILED,
        succeeded=False,
        error_code=INTERRUPTED,
        finished_at=timezone.now(),
    )
