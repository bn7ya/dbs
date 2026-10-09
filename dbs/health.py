from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from datetime import timedelta

from django.utils import timezone

OK = "ok"
INFO = "info"
WARN = "warn"
ERROR = "error"
SEVERITY = {INFO: 0, OK: 0, WARN: 1, ERROR: 2}

STALE_FACTOR = 1.5
LATE_FACTOR = 3
FREE_SPACE_FACTOR = 2
FREE_SPACE_SHARE = 0.05
FAILURE_WINDOW = timedelta(days=7)
SCHEDULER_SILENCE_TICKS = 3


@dataclass
class Check:
    name: str
    status: str
    message: str


@dataclass
class HealthReport:
    checks: list = field(default_factory=list)
    last_backup_at: object = None
    generated_at: object = None

    @property
    def status(self):
        worst = max((SEVERITY[check.status] for check in self.checks), default=0)
        return {0: OK, 1: WARN, 2: ERROR}[worst]

    def as_dict(self):
        return {
            "status": self.status,
            "checks": [
                {"name": c.name, "status": c.status, "message": c.message}
                for c in self.checks
            ],
            "last_backup_at": _iso(self.last_backup_at),
            "generated_at": _iso(self.generated_at),
        }


def _iso(moment):
    return moment.isoformat() if moment else None


def _age(delta):
    seconds = int(delta.total_seconds())
    if seconds < 3600:
        return f"{max(seconds // 60, 0)} minutes"
    if seconds < 86400 * 2:
        return f"{seconds // 3600} hours"
    return f"{seconds // 86400} days"


def report(now=None):
    from .models import BackupSchedule

    now = now or timezone.now()
    schedule = BackupSchedule.load()
    last_backup = _last_success("backup.create")
    result = HealthReport(
        last_backup_at=last_backup.created_at if last_backup else None,
        generated_at=now,
    )
    result.checks.append(_backup_age(schedule, last_backup, now))
    result.checks.append(_last_validation())
    result.checks.append(_newest_file())
    result.checks.extend(_backup_directory(last_backup))
    result.checks.append(_passphrase())
    result.checks.append(_scheduler(schedule, now))
    failure = _recent_failure(now)
    if failure is not None:
        result.checks.append(failure)
    return result


def _last_success(action):
    from .models import AuditEvent

    return AuditEvent.objects.filter(action=action, status="succeeded").first()


def _backup_age(schedule, last_backup, now):
    if last_backup is None:
        if schedule.enabled:
            return Check("last backup", ERROR, "No backup has been taken yet.")
        return Check("last backup", WARN, "No backup has been taken yet.")
    age = now - last_backup.created_at
    message = f"The last backup finished {_age(age)} ago."
    if not schedule.enabled:
        return Check("last backup", INFO, message + " Scheduled backups are off.")
    interval = timedelta(seconds=schedule.interval_seconds)
    if age <= interval * STALE_FACTOR:
        return Check("last backup", OK, message)
    if age <= interval * LATE_FACTOR:
        return Check("last backup", WARN, message + f" Expected every {schedule.interval}.")
    return Check("last backup", ERROR, message + f" Expected every {schedule.interval}.")


def _last_validation():
    from .models import AuditEvent

    event = AuditEvent.objects.filter(action="backup.validate").first()
    if event is None:
        return Check("last validation", INFO, "No backup has been validated yet.")
    if event.status == "failed":
        return Check(
            "last validation", ERROR, f"{event.target_name} failed validation: {event.detail}"
        )
    return Check("last validation", OK, f"{event.target_name} validated.")


def _inside(directory, location):
    root = os.path.realpath(directory)
    return os.path.dirname(os.path.realpath(location)) == root


def _newest_file():
    from .models import BackupRecord
    from .schedule_runner import backup_directory

    directory = backup_directory()
    if not directory:
        return Check("newest file", INFO, "DBS_BACKUP_DIR is not set.")
    for record in BackupRecord.objects.filter(target__isnull=True).exclude(location=""):
        if not _inside(directory, record.location):
            continue
        if os.path.isfile(record.location):
            return Check("newest file", OK, f"{record.filename} is on disk.")
        return Check("newest file", ERROR, f"{record.filename} is missing from {directory}.")
    return Check("newest file", INFO, f"No backup recorded in {directory} yet.")


def _backup_directory(last_backup):
    from .schedule_runner import backup_directory

    directory = backup_directory()
    if not directory:
        return [
            Check(
                "backup directory",
                WARN,
                "DBS_BACKUP_DIR is not set, so scheduled backups and restores from a "
                "stored backup are unavailable.",
            )
        ]
    probe = directory if os.path.isdir(directory) else os.path.dirname(directory) or "."
    if not os.path.isdir(probe) or not os.access(probe, os.W_OK):
        return [Check("backup directory", ERROR, f"{directory} is not writable.")]
    checks = [Check("backup directory", OK, f"{directory} is writable.")]
    usage = shutil.disk_usage(probe)
    needed = (last_backup.data.get("size", 0) if last_backup else 0) * FREE_SPACE_FACTOR
    free = f"{usage.free / 1024 ** 3:.1f} GiB free"
    if usage.free < needed or usage.free < usage.total * FREE_SPACE_SHARE:
        checks.append(Check("disk space", WARN, f"Only {free}."))
    else:
        checks.append(Check("disk space", OK, f"{free}."))
    return checks


def _passphrase():
    from .schedule_runner import unattended_passphrase

    if unattended_passphrase() is None:
        return Check(
            "passphrase", ERROR, "No passphrase: set SECRET_KEY or DBS_PASSPHRASE."
        )
    return Check("passphrase", OK, "A passphrase is available for unattended backups.")


def _scheduler(schedule, now):
    from . import leases
    from .schedule_runner import OFF, SEEN_LEASE, TICK_SECONDS, mode

    current = mode()
    if not schedule.enabled:
        return Check("scheduler", INFO, f"Scheduled backups are off ({current} mode).")
    if current == OFF:
        return Check(
            "scheduler", WARN, 'The schedule is on, but DBS_SCHEDULER is "off".'
        )
    seen = leases.last_renewed(SEEN_LEASE)
    silence = timedelta(seconds=TICK_SECONDS * SCHEDULER_SILENCE_TICKS)
    if seen is None or now - seen > silence:
        return Check(
            "scheduler",
            WARN,
            f"The scheduler has not checked in recently ({current} mode). "
            "It starts with the first request a worker serves, or with "
            "`manage.py dbs schedule`.",
        )
    return Check("scheduler", OK, f"The scheduler checked in {_age(now - seen)} ago.")


def _recent_failure(now):
    from .models import AuditEvent

    event = (
        AuditEvent.objects.filter(
            action__startswith="backup.", status="failed", created_at__gte=now - FAILURE_WINDOW
        )
        .first()
    )
    if event is None:
        return None
    return Check(
        "recent failure",
        WARN,
        f"{event.action} failed {_age(now - event.created_at)} ago: {event.detail}",
    )
