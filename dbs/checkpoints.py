from __future__ import annotations

import logging
import os
import shutil
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field

from django.core.management.base import CommandError
from django.db import DatabaseError, connections

from . import audit, retention
from .conf import setting
from .exceptions import BackupError, DBSError
from .io import can_write_into, nearest_existing
from .naming import backup_prefix, backup_stem
from .registry import ModelBackup

logger = logging.getLogger("dbs")

ACTION = "backup.checkpoint"
SETTING = "DBS_MIGRATION_CHECKPOINTS"
BEFORE_MIGRATE = "before-migrate"
AFTER_MIGRATE = "after-migrate"
BEFORE_RESTORE = "before-restore"
AFTER_RESTORE = "after-restore"
BEFORE_ROLES = (BEFORE_MIGRATE, BEFORE_RESTORE)
AFTER_ROLES = (AFTER_MIGRATE, AFTER_RESTORE)
ROLES = (BEFORE_MIGRATE, AFTER_MIGRATE, BEFORE_RESTORE, AFTER_RESTORE)
OWN_APP = "dbs"
TEST_PREFIX = "test_"
FREE_SPACE_FACTOR = 2
FREE_SPACE_SHARE = 0.05
SWITCH_OFF = "pass --no-checkpoint, or set DBS_MIGRATION_CHECKPOINTS = False"
FAILURES = (DBSError, OSError, DatabaseError)


class CheckpointError(BackupError):
    pass


@dataclass
class Checkpoint:
    name: str
    path: str
    role: str
    database: str
    plan: list = field(default_factory=list)
    size: int = 0


class Session(threading.local):
    def __init__(self):
        self.skip = False
        self.before: dict = {}


_session = Session()


@contextmanager
def session(*, skip: bool = False):
    previous = _session.skip, _session.before
    _session.skip, _session.before = skip, {}
    try:
        yield _session
    finally:
        _session.skip, _session.before = previous


def enabled() -> bool:
    return bool(setting(SETTING, True))


def directory():
    from .schedule_runner import backup_directory

    return backup_directory()


def stem(role: str, database: str) -> str:
    from .schedule_runner import backup_prefix_setting

    return f"{backup_stem(backup_prefix_setting(), database)}-{role}"


def role_of(name: str, database: str):
    prefix = backup_prefix(name)
    return next((role for role in ROLES if prefix == stem(role, database)), None)


def is_test_database(connection) -> bool:
    described = connection.settings_dict
    name = str(described.get("NAME") or "")
    if connection.vendor == "sqlite" and (not name or ":memory:" in name or "mode=memory" in name):
        return True
    test_name = (described.get("TEST") or {}).get("NAME")
    if test_name and name == str(test_name):
        return True
    return os.path.basename(name).startswith(TEST_PREFIX)


def is_fresh(connection) -> bool:
    from .engine import schema

    return not schema.has_applied_migrations(connection)


def plan_steps(plan) -> list:
    return [
        f"{'-' if backwards else ''}{migration.app_label}.{migration.name}"
        for migration, backwards in plan or ()
    ]


def take(role: str, *, using: str = "default", plan=(), protect=()) -> Checkpoint:
    from .engine import schema
    from .engine.backup import write_selection
    from .schedule_runner import (
        discard_reservation,
        reserve,
        unattended_passphrase,
        write_reserved,
    )

    folder = directory()
    if not folder:
        raise CheckpointError("DBS_BACKUP_DIR is not set, so a checkpoint has nowhere to go.")
    passphrase = unattended_passphrase()
    if passphrase is None:
        raise CheckpointError(
            "No passphrase encrypts a checkpoint: set SECRET_KEY or DBS_PASSPHRASE."
        )
    connection = connections[using]
    found = schema.snapshot(connection)
    carried = found.carried
    selection = [(model, ModelBackup()) for model in carried]
    header = {
        "applied": [list(key) for key in found.applied],
        "checkpoint": {"role": role, "plan": list(plan)},
        "schema": schema.schema_digest(carried),
    }
    os.makedirs(folder, exist_ok=True)
    name = reserve(folder, stem(role, using))
    output = os.path.join(folder, name)
    data = {"file": name, "database": using, "role": role, "migrations": list(plan)}
    try:
        with audit.track(ACTION, target=name, data=data) as entry:
            summary = write_reserved(
                output,
                passphrase,
                writer=lambda fh: write_selection(
                    fh, passphrase, selection, using=using, header=header
                ),
            )
            entry.data.update(
                size=summary.bytes_written,
                sha256=summary.sha256,
                verified=True,
                compressed=True,
                records=summary.records,
            )
            audit.record_backup(
                output, summary.bytes_written, summary.sha256, using, note=note_of(role, plan)
            )
    finally:
        discard_reservation(output)
    logger.info("checkpoint wrote %s (%d bytes)", output, summary.bytes_written)
    try:
        prune(folder, using, protect=(name, *protect))
    except DatabaseError as exc:
        logger.warning("could not prune older checkpoints: %s", exc)
    return Checkpoint(name, output, role, using, list(plan), summary.bytes_written)


def note_of(role: str, plan) -> str:
    moment, what = role.split("-", 1)
    steps = ", ".join(plan)
    return f"Checkpoint {moment} a {what}" + (f": {steps}" if steps else "")


def group(folder: str, database: str) -> list:
    from .schedule_runner import stored_backups

    return [
        stored for role in ROLES for stored in stored_backups(folder, stem(role, database))
    ]


def newest(stored: list, database: str, roles):
    found = [backup for backup in stored if role_of(backup.name, database) in roles]
    return max(found, key=lambda backup: (backup.moment, backup.name), default=None)


def prune(folder: str, database: str, protect=()) -> list:
    from .schedule_runner import remove_stale

    stored = group(folder, database)
    pair = (newest(stored, database, BEFORE_ROLES), newest(stored, database, AFTER_ROLES))
    protected = {os.path.basename(name) for name in protect if name}
    protected |= {backup.name for backup in pair if backup is not None}
    keep = retention.maximum_keep()
    return remove_stale(folder, retention.stale_beyond_limit(stored, keep, protected), keep)


def listing(databases=None) -> list:
    from .models import AuditEvent

    folder = directory()
    if not folder:
        return []
    found = []
    for database in databases or list(connections):
        for stored in group(folder, database):
            path = os.path.join(folder, stored.name)
            found.append(
                {
                    "name": stored.name,
                    "path": path,
                    "role": role_of(stored.name, database),
                    "database": database,
                    "taken_at": stored.moment.isoformat(),
                    "size": os.path.getsize(path),
                    "migrations": None,
                }
            )
    try:
        recorded = dict(
            AuditEvent.objects.filter(
                action=ACTION,
                status=audit.SUCCEEDED,
                target_name__in=[entry["name"] for entry in found],
            )
            .order_by("created_at", "pk")
            .values_list("target_name", "data")
        )
    except DatabaseError:
        recorded = {}
    for entry in found:
        data = recorded.get(entry["name"])
        if isinstance(data, dict) and isinstance(data.get("migrations"), list):
            entry["migrations"] = data["migrations"]
    return sorted(found, key=lambda entry: (entry["taken_at"], entry["name"]))


def restore_running() -> bool:
    from . import jobs, leases
    from .models import AuditEvent

    try:
        running = list(
            AuditEvent.objects.filter(
                action=jobs.RESTORE, status__in=audit.UNFINISHED
            ).values_list("pk", flat=True)
        )
        return any(leases.holder(jobs.job_lease(event_id)) is not None for event_id in running)
    except DatabaseError:
        return False


@dataclass
class Readiness:
    problems: list = field(default_factory=list)
    notes: list = field(default_factory=list)


def readiness(using: str = "default") -> Readiness:
    from .schedule_runner import unattended_passphrase

    found = Readiness()
    folder = directory()
    if not can_write_into(folder):
        found.problems.append(f"{folder} is not a folder this process can write into")
    if unattended_passphrase() is None:
        found.problems.append("no passphrase encrypts a checkpoint: set SECRET_KEY or DBS_PASSPHRASE")
    if found.problems:
        return found
    usage = shutil.disk_usage(nearest_existing(folder))
    newest_size = max((entry["size"] for entry in listing([using])), default=0)
    if usage.free < newest_size * FREE_SPACE_FACTOR:
        found.problems.append(
            f"{folder} has {usage.free / 1024 ** 2:.0f} MiB free, less than the two checkpoints "
            f"a migration writes ({newest_size * FREE_SPACE_FACTOR / 1024 ** 2:.0f} MiB)"
        )
    elif usage.free < usage.total * FREE_SPACE_SHARE:
        found.notes.append(f"{folder} is nearly full: {usage.free / 1024 ** 3:.1f} GiB free")
    if restore_running():
        found.notes.append("a restore is running; a migration would wait for it")
    return found


def skip_reason(using: str, plan):
    if not plan:
        return ""
    if all(migration.app_label == OWN_APP for migration, _backwards in plan):
        return ""
    return standing_reason(using)


def standing_reason(using: str):
    if _session.skip or not enabled():
        return ""
    connection = connections[using]
    if is_test_database(connection) or is_fresh(connection):
        return ""
    if not directory():
        return (
            "DBS keeps no checkpoint here: DBS_BACKUP_DIR is not set, so there is no backup "
            "to go back to."
        )
    return None


def say(stdout, message: str) -> None:
    (stdout or sys.stdout).write(message + "\n")


def before_migrate(sender, *, using, plan=None, verbosity=1, stdout=None, **kwargs):
    reason = skip_reason(using, plan)
    if reason is not None:
        if reason and verbosity >= 1:
            say(stdout, reason)
        return
    if restore_running():
        raise CommandError(
            "A restore is running in this project, so the migration did not start. "
            f"Run it again when the restore has finished, or {SWITCH_OFF}."
        )
    try:
        checkpoint = take(BEFORE_MIGRATE, using=using, plan=plan_steps(plan))
    except FAILURES as exc:
        raise CommandError(
            "DBS could not keep a checkpoint of the database before this migration, so "
            f"the migration did not start: {exc} To migrate without one, {SWITCH_OFF}."
        ) from exc
    _session.before[using] = checkpoint
    if verbosity >= 1:
        say(stdout, f"Checkpoint before this migration: {checkpoint.path}")


def after_migrate(sender, *, using, plan=None, verbosity=1, stdout=None, **kwargs):
    before = _session.before.pop(using, None)
    if before is None:
        return
    try:
        checkpoint = take(AFTER_MIGRATE, using=using, plan=before.plan, protect=(before.name,))
    except FAILURES as exc:
        logger.warning("could not keep a checkpoint after the migration: %s", exc)
        sys.stderr.write(
            "The migration is applied, but DBS could not keep a checkpoint of the database "
            f"after it: {exc}\n"
        )
        return
    if verbosity >= 1:
        say(stdout, f"Checkpoint after this migration: {checkpoint.path}")


def restore_hint(checkpoint: Checkpoint) -> str:
    alias = "" if checkpoint.database == "default" else f" --database {checkpoint.database}"
    return (
        f"The database as it was before this migration is kept in {checkpoint.path}. "
        "To put it back, schema and rows:\n"
        f'  python manage.py dbs restore "{checkpoint.path}" --flush{alias}'
    )


def require_ready(using: str = "default", stdout=None) -> None:
    if _session.skip or not enabled() or is_test_database(connections[using]):
        return
    if not directory():
        say(
            stdout,
            "DBS will keep no checkpoint of the next migration: DBS_BACKUP_DIR is not set.",
        )
        return
    found = readiness(using)
    for note in found.notes:
        say(stdout, f"DBS: {note}.")
    if found.problems:
        raise CommandError(
            "DBS is not ready to keep a checkpoint of the next migration, so no migration "
            "was written: " + "; ".join(found.problems) + f". Fix that, or {SWITCH_OFF}."
        )


def restore(
    path,
    passphrase: str,
    *,
    using: str = "default",
    checkpoint: bool = True,
    stdout=None,
    **options,
):
    from .engine.restore import preflight, restore_backup

    wanted = (
        checkpoint
        and not options.get("dry_run")
        and options.get("load_data", True)
        and isinstance(path, (str, os.PathLike))
    )
    reason = standing_reason(using) if wanted else ""
    if reason is not None:
        if reason:
            say(stdout, reason)
        return restore_backup(path, passphrase, using=using, **options)
    preflight(path, passphrase, using=using, **options)
    source = os.path.basename(os.fspath(path))
    try:
        before = take(BEFORE_RESTORE, using=using, protect=(source,))
    except FAILURES as exc:
        raise CheckpointError(
            "DBS could not keep a checkpoint of the database before this restore, so the "
            f"restore did not start: {exc} To restore without one, pass --no-checkpoint."
        ) from exc
    say(stdout, f"Checkpoint before this restore: {before.path}")
    result = restore_backup(path, passphrase, using=using, **options)
    try:
        after = take(AFTER_RESTORE, using=using, protect=(source, before.name))
    except FAILURES as exc:
        logger.warning("could not keep a checkpoint after the restore: %s", exc)
        sys.stderr.write(
            f"The restore is done, but DBS could not keep a checkpoint after it: {exc}\n"
        )
    else:
        say(stdout, f"Checkpoint after this restore: {after.path}")
    return result
