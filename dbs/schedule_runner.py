from __future__ import annotations

import hashlib
import logging
import os
import threading
from datetime import timedelta

from django.db import DatabaseError, close_old_connections
from django.db.models import Q
from django.utils import timezone

from . import audit, leases
from .conf import setting
from .exceptions import DBSError
from .naming import DEFAULT_PREFIX, backup_filename
from .retention import prune_directory, prune_remote

logger = logging.getLogger("dbs")

SCHEDULE_LEASE = "dbs.schedule"
SEEN_LEASE = "dbs.scheduler.seen"
TICK_SECONDS = 60
LONGEST_RUN_SECONDS = 6 * 3600
MINIMUM_INTERVAL_SECONDS = 300
THREAD = "thread"
COMMAND = "command"
OFF = "off"
MODES = (THREAD, COMMAND, OFF)

_started_in = {"pid": None}
_start_lock = threading.Lock()
stop_event = threading.Event()


class ScheduleError(DBSError):
    pass


def mode():
    return str(setting("DBS_SCHEDULER", THREAD)).strip().lower()


def unattended_passphrase():
    from ._cli import configured_passphrase
    from .keys import default_passphrase, has_default_passphrase

    configured = configured_passphrase()
    if configured:
        return configured
    if has_default_passphrase():
        return default_passphrase()
    return None


def backup_directory():
    directory = setting("DBS_BACKUP_DIR", None)
    if not directory:
        return None
    return os.path.expanduser(str(directory))


def available_name(directory, prefix):
    for ordinal in range(1, 1000):
        name = backup_filename(prefix, ordinal=ordinal)
        if not os.path.exists(os.path.join(directory, name)):
            return name
    raise ScheduleError("Cannot find an unused backup filename for this second.")


def run_cycle(passphrase, plan):
    from .engine import create_backup

    os.makedirs(plan["output_dir"], exist_ok=True)
    name = available_name(plan["output_dir"], plan["prefix"])
    output = os.path.join(plan["output_dir"], name)
    extra = {"block_size": plan["block_size"]} if plan.get("block_size") else {}
    with audit.track(
        "backup.create",
        target=name,
        data={"file": name, "database": plan["database"]},
    ) as entry:
        container = create_backup(
            passphrase,
            using=plan["database"],
            compress=plan["compress"],
            verify=plan["verify"],
            kdf_params=plan.get("kdf_params"),
            output=output,
            **extra,
        )
        digest = hashlib.sha256(container).hexdigest()
        entry.data.update(
            size=len(container),
            sha256=digest,
            verified=plan["verify"],
            compressed=plan["compress"],
        )
        audit.record_backup(output, container, digest, plan["database"])
    logger.info("scheduled backup wrote %s (%d bytes)", output, len(container))

    removed = prune_directory(plan["output_dir"], plan["keep"], plan["prefix"])
    if removed:
        audit.safe_record(
            "backup.prune",
            target=plan["output_dir"],
            data={"removed": removed, "keep": plan["keep"]},
        )
    if plan.get("push") is not None:
        push(name, output, plan)
    return output


def push(name, output, plan):
    from .transports.ssh import open_session

    with audit.track("backup.push", target=name, data={"file": name}) as entry:
        with open_session(plan["push"]) as session:
            entry.data["remote"] = session.push(output, name)
            if plan.get("keep_remote") is not None:
                removed = prune_remote(session, plan["keep_remote"], plan["prefix"])
                entry.data["removed"] = removed


def push_target(schedule):
    if schedule.push_target_id:
        return schedule.push_target.ssh_target()
    name = setting("DBS_SCHEDULE_PUSH_TARGET", None)
    if not name:
        return None
    from .transports.ssh import SSHTarget

    return SSHTarget.from_settings(name)


def schedule_plan(schedule):
    directory = backup_directory()
    if not directory:
        raise ScheduleError("Set DBS_BACKUP_DIR so scheduled backups have a home.")
    return {
        "interval": schedule.interval,
        "output_dir": directory,
        "prefix": setting("DBS_BACKUP_PREFIX", DEFAULT_PREFIX),
        "keep": schedule.keep,
        "keep_remote": schedule.keep_remote,
        "push": push_target(schedule),
        "database": schedule.database,
        "compress": True,
        "verify": True,
        "block_size": None,
        "kdf_params": None,
    }


def database_schedule():
    from .models import BackupSchedule

    try:
        return BackupSchedule.load()
    except DatabaseError:
        return None


def run_due(*, force=False, now=None):
    from .models import BackupSchedule

    schedule = BackupSchedule.load()
    if not schedule.enabled and not force:
        return None
    now = now or timezone.now()
    if not force and schedule.next_run_at and schedule.next_run_at > now:
        return None
    owner = f"{leases.process_owner()}:{threading.get_ident()}"
    if not leases.acquire(SCHEDULE_LEASE, owner, LONGEST_RUN_SECONDS):
        return None
    try:
        claimed = BackupSchedule.objects.filter(pk=schedule.pk)
        if not force:
            claimed = claimed.filter(Q(next_run_at__isnull=True) | Q(next_run_at__lte=now))
        following = now + timedelta(seconds=schedule.interval_seconds)
        if not claimed.update(next_run_at=following):
            return None
        return _run(schedule)
    finally:
        leases.release(SCHEDULE_LEASE, owner)


def _run(schedule):
    from .models import BackupSchedule

    try:
        passphrase = unattended_passphrase()
        if passphrase is None:
            raise ScheduleError(
                "Scheduled backups have no passphrase: set SECRET_KEY or DBS_PASSPHRASE."
            )
        output = run_cycle(passphrase, schedule_plan(schedule))
    except Exception as exc:
        BackupSchedule.objects.filter(pk=schedule.pk).update(
            last_run_at=timezone.now(), last_status=audit.FAILED, last_error=str(exc)[:4000]
        )
        raise
    BackupSchedule.objects.filter(pk=schedule.pk).update(
        last_run_at=timezone.now(), last_status=audit.SUCCEEDED, last_error=""
    )
    return output


def tick():
    close_old_connections()
    try:
        leases.acquire(SEEN_LEASE, leases.process_owner(), TICK_SECONDS * 3)
        return run_due()
    except DatabaseError as exc:
        logger.debug("the backup schedule could not be read: %s", exc)
    except Exception as exc:
        logger.exception("scheduled backup failed: %s", exc)
    finally:
        close_old_connections()
    return None


def _loop():
    while not stop_event.is_set():
        tick()
        if stop_event.wait(TICK_SECONDS):
            break


def ensure_started(**kwargs):
    if mode() != THREAD:
        return False
    pid = os.getpid()
    with _start_lock:
        if _started_in["pid"] == pid:
            return False
        _started_in["pid"] = pid
    threading.Thread(target=_loop, name="dbs-scheduler", daemon=True).start()
    return True
