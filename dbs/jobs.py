from __future__ import annotations

import logging
import threading
from contextlib import contextmanager

from django.db import connections
from django.utils import timezone

from . import audit, leases
from .exceptions import DBSError

logger = logging.getLogger("dbs")

RUNNER_LEASE = "dbs.runner"
JOB_LEASE_PREFIX = "dbs.job:"
LEASE_SECONDS = 120
HEARTBEAT_SECONDS = 30
DETAIL_MAX = 4000

_runs_here = threading.Lock()


class Busy(DBSError):
    code = "busy"


def job_lease(event_id):
    return f"{JOB_LEASE_PREFIX}{event_id}"


class Runner:
    def __init__(self):
        self.owner = leases.unique_owner()
        self.held = False

    def take(self):
        recover()
        if not _runs_here.acquire(blocking=False):
            raise Busy("A backup or restore is already running in this process.")
        try:
            taken = leases.acquire(RUNNER_LEASE, self.owner, LEASE_SECONDS)
        except BaseException:
            _runs_here.release()
            raise
        if not taken:
            _runs_here.release()
            raise Busy("Another backup or restore is running; try again when it finishes.")
        self.held = True
        return self

    def release(self):
        if not self.held:
            return
        self.held = False
        try:
            leases.release(RUNNER_LEASE, self.owner)
        finally:
            _runs_here.release()


class Job:
    def __init__(self, event, owner, hold=()):
        self.event_id = event.pk
        self.target = event.target_name
        self.data = dict(event.data or {})
        self.owner = owner
        self.lease = job_lease(event.pk)
        self.held = [self.lease, *hold]

    @classmethod
    def begin(cls, action, *, target, data, owner, hold=(), actor=None, remote_addr=""):
        event = audit.record(
            action,
            actor=actor,
            target=target,
            data=data,
            status=audit.RUNNING,
            remote_addr=remote_addr,
        )
        leases.acquire(job_lease(event.pk), owner, LEASE_SECONDS)
        return cls(event, owner, hold)

    def heartbeat(self):
        return leases.Heartbeat(self.held, self.owner, LEASE_SECONDS, HEARTBEAT_SECONDS)

    def succeed(self):
        audit.finish(self.event_id, data=self.data)

    def fail(self, exc):
        audit.fail(
            self.event_id,
            audit.error_code_for(exc),
            data=self.data,
            detail=str(exc)[:DETAIL_MAX] or type(exc).__name__,
        )

    def close(self):
        leases.drop(self.lease, self.owner)

    @contextmanager
    def tracked(self):
        try:
            with self.heartbeat():
                yield self
        except BaseException as exc:
            self.fail(exc)
            raise
        else:
            self.succeed()
        finally:
            self.close()


def recover(now=None):
    from .models import Lease

    now = now or timezone.now()
    expired = list(
        Lease.objects.filter(
            name__startswith=JOB_LEASE_PREFIX, expires_at__lte=now
        ).values_list("name", flat=True)
    )
    if not expired:
        return 0
    events = [
        int(name[len(JOB_LEASE_PREFIX):])
        for name in expired
        if name[len(JOB_LEASE_PREFIX):].isdigit()
    ]
    interrupted = audit.interrupt(events=events) if events else 0
    Lease.objects.filter(name__in=expired, expires_at__lte=now).delete()
    if interrupted:
        logger.warning("%d DBS job(s) stopped before they finished", interrupted)
    return interrupted


def launch(work, name="dbs-job"):
    def run():
        try:
            work()
        except Exception:
            logger.exception("a DBS job failed")
        finally:
            connections.close_all()

    thread = threading.Thread(target=run, name=name, daemon=True)
    thread.start()
    return thread
