from __future__ import annotations

from datetime import datetime, timedelta
from typing import cast

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from dbs.manager.activity.services import ActivityService, sweep_stale_jobs
from dbs.manager.backups.exceptions import BackupRunning
from dbs.manager.backups.locks import TakeLock
from dbs.manager.backups.models import BackupPlan
from dbs.manager.backups.repositories import BackupFileRepository, BackupPlanRepository
from dbs.manager.backups.services.actions import Action
from dbs.manager.backups.services.backup_run_service import BackupRunService
from dbs.manager.backups.services.job_queue import JobQueue
from dbs.manager.backups.services.plan_runs import last_run, run_detail
from dbs.manager.backups.storage import BackupStorage
from dbs.manager.runner import get_runner
from dbs.models import AuditEvent

STALE_UPLOAD_AFTER = timedelta(days=1)


def following(scheduled: datetime, interval: timedelta, now: datetime) -> datetime:
    return scheduled + ((now - scheduled) // interval + 1) * interval


class BackupScheduleService:
    def __init__(self) -> None:
        self.plans = BackupPlanRepository()
        self.files = BackupFileRepository()
        self.activity = ActivityService(None)
        self.jobs = JobQueue(None)
        self.storage = BackupStorage()
        self.locks = TakeLock()

    def dispatch_due(self) -> None:
        now = timezone.now()
        with transaction.atomic():
            for plan in self.plans.lock_scheduled_by(now):
                self.plans.update(
                    plan,
                    next_run_at=following(
                        cast(datetime, plan.next_run_at),
                        timedelta(minutes=cast(int, plan.interval_minutes)),
                        now,
                    ),
                )
                job = self.activity.queue(
                    Action.RUN,
                    server=plan.server,
                    target=plan.name,
                    detail=run_detail(plan),
                )
                transaction.on_commit(
                    lambda job=job, plan=plan: self._start(job, plan),
                    robust=True,
                )

    def remove_expired(self) -> None:
        now = timezone.now()
        self.storage.remove_stale_uploads(before=now - STALE_UPLOAD_AFTER)
        expired = list(
            self.files.deleted_before(now - timedelta(days=settings.BACKUP_GRACE_DAYS))
        )
        for file in expired:
            self.storage.remove(file.storage_path)
            self.files.update(file, removed_at=now)
        if expired:
            self.activity.record(Action.EXPIRE, detail={"removed": len(expired)})

    def sweep_stale_jobs(self) -> None:
        sweep_stale_jobs()

    def _start(self, job: AuditEvent, plan: BackupPlan) -> None:
        if not self.locks.acquire(plan.server_id, job.pk):
            self.activity.fail(job.pk, BackupRunning())
            self.plans.update(plan, **last_run(self.activity.get(job.pk)))
            return
        self.jobs.send(
            job,
            lambda job: get_runner().submit(
                BackupRunService().run_plan, job.pk, plan.pk
            ),
            on_failure=lambda: self.locks.release(plan.server_id, job.pk),
        )


def dispatch_due_plans() -> None:
    BackupScheduleService().dispatch_due()


def remove_expired_files() -> None:
    BackupScheduleService().remove_expired()
