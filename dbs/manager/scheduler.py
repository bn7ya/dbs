from __future__ import annotations

import logging
import threading
from datetime import timedelta

from django.db import close_old_connections
from django.utils import timezone
from django.utils.module_loading import import_string

from dbs import leases

from .conf import INSTANCE_LEASE, LEASE_SECONDS
from .runner import get_runner

logger = logging.getLogger("dbs.manager")

TICK_SECONDS = 30

TASKS = {
    "dispatch_due_plans": (
        timedelta(minutes=1),
        "dbs.manager.backups.services.backup_schedule_service.dispatch_due_plans",
    ),
    "remove_expired_files": (
        timedelta(days=1),
        "dbs.manager.backups.services.backup_schedule_service.remove_expired_files",
    ),
    "snapshot_env_files": (
        timedelta(days=1),
        "dbs.manager.envfiles.services.env_snapshot_service.snapshot_env_files",
    ),
    "sweep_stale_jobs": (
        timedelta(minutes=15),
        "dbs.manager.activity.services.sweep_stale_jobs",
    ),
}


def owner():
    return leases.process_owner()


def run_task(name):
    _, handler = TASKS[name]
    return import_string(handler)()


def claim(name, scheduled, following):
    from .models import ScheduledTask

    return (
        ScheduledTask.objects.filter(name=name, next_run_at=scheduled).update(
            next_run_at=following
        )
        == 1
    )


def tick(now=None):
    from .models import ScheduledTask

    now = now or timezone.now()
    if not leases.acquire(INSTANCE_LEASE, owner(), LEASE_SECONDS):
        return []
    dispatched = []
    for task in ScheduledTask.objects.filter(next_run_at__lte=now):
        if task.name not in TASKS:
            continue
        interval, _ = TASKS[task.name]
        if not claim(task.name, task.next_run_at, now + interval):
            continue
        get_runner().submit(run_task, task.name)
        dispatched.append(task.name)
    return dispatched


class Scheduler:
    def __init__(self, interval=TICK_SECONDS):
        self.interval = interval
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(
                target=self._loop, name="dbs-manager-scheduler", daemon=True
            )
            self.thread.start()
        return self

    def stop(self, timeout=5):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout)
            self.thread = None

    def _loop(self):
        while not self.stop_event.is_set():
            self.safe_tick()
            if self.stop_event.wait(self.interval):
                break

    def safe_tick(self):
        close_old_connections()
        try:
            return tick()
        except Exception as exc:
            logger.exception("the scheduler tick failed: %s", exc)
            return []
        finally:
            close_old_connections()
