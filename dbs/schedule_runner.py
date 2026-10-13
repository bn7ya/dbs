from __future__ import annotations

import hashlib
import logging
import os
import threading
from datetime import timedelta, timezone as dt_timezone

from django.db import DatabaseError, close_old_connections
from django.db.models import Q
from django.utils import timezone

from . import audit, leases, retention
from .conf import setting
from .exceptions import DBSError
from .naming import DEFAULT_PREFIX, backup_stem, parse_backup_moment, reserve_backup_name

logger = logging.getLogger("dbs")

SCHEDULE_LEASE = "dbs.schedule"
SEEN_LEASE = "dbs.scheduler.seen"
TICK_SECONDS = 60
LONGEST_RUN_SECONDS = 6 * 3600
MINIMUM_INTERVAL_SECONDS = 300
VERIFYING_ACTIONS = ("backup.create", "backup.validate")
VERIFICATION_FAILURES = ("CorruptionError", "ContainerError")
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


def backup_prefix_setting():
    return str(setting("DBS_BACKUP_PREFIX", DEFAULT_PREFIX))


def reserve(directory, stem):
    try:
        return reserve_backup_name(directory, stem)
    except FileExistsError as exc:
        raise ScheduleError(str(exc)) from exc


def discard_reservation(path):
    try:
        if os.path.getsize(path) == 0:
            os.remove(path)
    except OSError:
        pass


def run_cycle(passphrase, plan):
    from .engine import create_backup

    os.makedirs(plan["output_dir"], exist_ok=True)
    stem = backup_stem(plan["prefix"], plan["database"])
    name = reserve(plan["output_dir"], stem)
    output = os.path.join(plan["output_dir"], name)
    extra = {"block_size": plan["block_size"]} if plan.get("block_size") else {}
    try:
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
    finally:
        discard_reservation(output)
    logger.info("scheduled backup wrote %s (%d bytes)", output, len(container))
    keep_newest(plan["output_dir"], stem, plan["keep"])
    return output


def _utc(moment):
    if timezone.is_naive(moment):
        moment = timezone.make_aware(moment)
    return moment.astimezone(dt_timezone.utc)


def recorded_moments(directory, names):
    from .models import BackupRecord

    root = os.path.realpath(directory)
    moments = {}
    records = (
        BackupRecord.objects.filter(filename__in=names)
        .exclude(location="")
        .order_by("created_at", "pk")
        .values_list("filename", "location", "created_at")
    )
    for filename, location, created_at in records:
        if os.path.dirname(os.path.realpath(location)) == root:
            moments[filename] = _utc(created_at)
    return moments


def _verdict(action, status, error_code, data):
    if action == "backup.validate":
        if data.get("ok") is True:
            return retention.PASSED
        if data.get("ok") is False:
            return retention.FAILED
        return None
    if status == audit.SUCCEEDED:
        return retention.PASSED if data.get("verified") else None
    if error_code in VERIFICATION_FAILURES:
        return retention.FAILED
    return None


def verification_states(names):
    from .models import AuditEvent

    states = {}
    events = (
        AuditEvent.objects.filter(
            action__in=VERIFYING_ACTIONS, target_name__in=names, status__in=audit.FINISHED
        )
        .order_by("created_at", "pk")
        .values_list("target_name", "action", "status", "error_code", "data")
    )
    for name, action, status, error_code, data in events:
        verdict = _verdict(action, status, error_code, data if isinstance(data, dict) else {})
        if verdict is not None:
            states[name] = verdict
    return states


def stored_backups(directory, stem):
    try:
        listed = os.listdir(directory)
    except OSError:
        return []
    names = retention.current_backup_names(listed, stem)
    moments = recorded_moments(directory, names)
    states = verification_states(names)
    stored = []
    for name in names:
        path = os.path.join(directory, name)
        if os.path.islink(path) or not os.path.isfile(path):
            continue
        is_container, created = retention.read_created(path)
        if not is_container:
            continue
        moment = moments.get(name) or created or parse_backup_moment(name)
        stored.append(
            retention.StoredBackup(name, moment, states.get(name, retention.UNKNOWN))
        )
    return stored


def keep_newest(directory, stem, keep):
    stale = retention.stale_stored_backups(stored_backups(directory, stem), keep)
    removed = retention.remove_backups(directory, stale)
    if removed:
        audit.safe_record(
            "backup.prune", target=directory, data={"removed": removed, "keep": keep}
        )
    return removed


def schedule_plan(schedule):
    from .models import BackupSchedule

    directory = backup_directory()
    if not directory:
        raise ScheduleError("Set DBS_BACKUP_DIR so scheduled backups have a home.")
    return {
        "interval": schedule.interval,
        "output_dir": directory,
        "prefix": backup_prefix_setting(),
        "keep": BackupSchedule.seed_keep(schedule.keep),
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
