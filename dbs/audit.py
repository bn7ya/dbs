from __future__ import annotations

import datetime
import errno
import hashlib
import json
import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass

from django.db import DatabaseError, IntegrityError, router, transaction
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
UNEXPECTED = "unexpected"
DISK_FULL = "disk_full"
PERMISSION_DENIED = "permission_denied"
READ_ONLY = "read_only"
DATABASE_FAILED = "database_failed"
OS_ERROR_CODES = {
    errno.ENOSPC: DISK_FULL,
    errno.EDQUOT: DISK_FULL,
    errno.EACCES: PERMISSION_DENIED,
    errno.EPERM: PERMISSION_DENIED,
    errno.EROFS: READ_ONLY,
}
USERNAME_KEY = "actor_username"

ACTION_MAX = 64
TARGET_MAX = 1024
DETAIL_MAX = 4000
ADDRESS_MAX = 64
ERROR_CODE_MAX = 64
SUBJECT_MAX = 64

CHAIN_LOCK = "dbs.audit.chain"
SEAL_BATCH = 200
CHAINED_FIELDS = (
    "action",
    "target_name",
    "detail",
    "data",
    "status",
    "error_code",
    "subject",
    "remote_addr",
    "succeeded",
    "started_at",
    "finished_at",
    "created_at",
)


def _known_actor(actor):
    if actor is None or not getattr(actor, "is_authenticated", False):
        return None
    return actor if getattr(actor, "pk", None) else None


def with_actor(data, actor):
    merged = dict(data or {})
    known = _known_actor(actor)
    if known is not None:
        merged.setdefault(USERNAME_KEY, known.get_username())
    return merged


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
    event = AuditEvent.objects.create(
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
    if status in FINISHED:
        seal_after_commit()
    return event


def safe_record(action, **fields):
    try:
        with transaction.atomic():
            return record(action, **fields)
    except DatabaseError as exc:
        logger.warning("Could not write the %s audit entry: %s", action, exc)
        return None


def error_code_for(exc):
    from django.core.management.base import CommandError

    from .exceptions import DBSError

    code = getattr(exc, "code", None)
    if isinstance(code, str) and code:
        return code
    if isinstance(exc, DBSError):
        return type(exc).__name__
    if isinstance(exc, OSError) and exc.errno in OS_ERROR_CODES:
        return OS_ERROR_CODES[exc.errno]
    if isinstance(exc, DatabaseError):
        return DATABASE_FAILED
    cause = exc.__cause__
    if isinstance(cause, DBSError) or (
        isinstance(cause, OSError) and cause.errno in OS_ERROR_CODES
    ):
        return error_code_for(cause)
    if isinstance(exc, CommandError):
        return type(exc).__name__
    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
        return INTERRUPTED
    return UNEXPECTED


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


def record_backup(output, size, digest, database, *, created_by=None, note=""):
    from .models import BackupRecord

    try:
        with transaction.atomic():
            return BackupRecord.objects.create(
                filename=os.path.basename(output),
                size_bytes=size,
                sha256=digest,
                database=database,
                location=os.path.abspath(output),
                created_by=_known_actor(created_by),
                note=note or "",
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
    closed = AuditEvent.objects.filter(pk=event_id, status__in=UNFINISHED).update(**fields)
    if closed:
        seal_after_commit()
    return closed


def interrupt(*, idle_since=None, keep=(), events=None):
    from .models import AuditEvent

    queued = Q(status=QUEUED)
    running = Q(status=RUNNING)
    if idle_since is not None:
        queued &= Q(created_at__lt=idle_since)
        running &= Q(started_at__lt=idle_since)
    unfinished = AuditEvent.objects.filter(queued | running).exclude(pk__in=keep)
    if events is not None:
        unfinished = unfinished.filter(pk__in=events)
    interrupted = unfinished.update(
        status=FAILED,
        succeeded=False,
        error_code=INTERRUPTED,
        finished_at=timezone.now(),
    )
    if interrupted:
        seal_after_commit()
    return interrupted


def _plain(value):
    if isinstance(value, datetime.datetime):
        if timezone.is_aware(value):
            value = value.astimezone(datetime.timezone.utc)
        return value.isoformat()
    return value


def canonical(event):
    body = {name: _plain(getattr(event, name)) for name in CHAINED_FIELDS}
    body["chain_index"] = event.chain_index
    return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)


def link(previous_hash, event):
    return hashlib.sha256((previous_hash + canonical(event)).encode("utf-8")).hexdigest()


def _hold_chain(alias):
    from .models import Lease

    now = timezone.now()
    locks = Lease.objects.using(alias).filter(name=CHAIN_LOCK)
    if locks.update(renewed_at=now):
        return
    try:
        with transaction.atomic(using=alias):
            Lease.objects.using(alias).create(name=CHAIN_LOCK, owner="", expires_at=now)
    except IntegrityError:
        locks.update(renewed_at=now)


def seal_pending(limit=SEAL_BATCH):
    from .models import AuditEvent

    alias = router.db_for_write(AuditEvent)
    with transaction.atomic(using=alias):
        _hold_chain(alias)
        events = AuditEvent.objects.using(alias)
        pending = list(
            events.filter(chain_index__isnull=True, status__in=FINISHED).order_by("pk")[:limit]
        )
        if not pending:
            return 0
        last = (
            events.filter(chain_index__isnull=False)
            .order_by("-chain_index")
            .values_list("chain_index", "chain_hash")
            .first()
        )
        index, previous = last or (0, "")
        for event in pending:
            index += 1
            event.chain_index = index
            event.chain_hash = link(previous, event)
            events.filter(pk=event.pk, chain_index__isnull=True).update(
                chain_index=index, chain_hash=event.chain_hash
            )
            previous = event.chain_hash
    return len(pending)


def _seal_quietly():
    try:
        seal_pending()
    except DatabaseError as exc:
        logger.warning("Could not seal the audit trail: %s", exc)


def seal_after_commit():
    from .models import AuditEvent

    transaction.on_commit(_seal_quietly, using=router.db_for_write(AuditEvent))


@dataclass
class ChainCheck:
    checked: int = 0
    head: str = ""
    broken_at: int | None = None
    event_id: int | None = None
    reason: str = ""
    unsealed: int = 0
    unfinished: int = 0

    @property
    def intact(self):
        return self.broken_at is None


def verify_chain():
    from .models import AuditEvent

    check = ChainCheck()
    previous, expected = "", 1
    sealed = AuditEvent.objects.filter(chain_index__isnull=False).order_by("chain_index", "pk")
    for event in sealed.iterator():
        if event.chain_index != expected:
            check.broken_at, check.event_id = expected, event.pk
            if event.chain_index < expected:
                check.reason = f"link {event.chain_index} appears twice (row {event.pk})"
            else:
                check.reason = (
                    f"links {expected} to {event.chain_index - 1} are missing before row "
                    f"{event.pk}: rows were deleted or unsealed"
                )
            return check
        if link(previous, event) != event.chain_hash:
            check.broken_at, check.event_id = expected, event.pk
            check.reason = f"row {event.pk} was changed after it was sealed"
            return check
        previous, expected = event.chain_hash, expected + 1
        check.checked += 1
    check.head = previous
    check.unsealed = AuditEvent.objects.filter(
        chain_index__isnull=True, status__in=FINISHED
    ).count()
    check.unfinished = AuditEvent.objects.filter(status__in=UNFINISHED).count()
    return check
