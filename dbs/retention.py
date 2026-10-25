from __future__ import annotations

import datetime
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Iterable

from .exceptions import ConfigurationError, ContainerError
from .naming import is_backup_name, parse_backup_moment, sorted_backups

logger = logging.getLogger("dbs")

MAXIMUM_KEEP = 5
PASSED = "passed"
FAILED = "failed"
UNKNOWN = "unknown"
LEFTOVER_SECONDS = 3600

_LEFTOVER_PATTERN = re.compile(r"^\..+\.dbs\.[A-Za-z0-9_]{8}(?:\.partial)?$")


@dataclass(frozen=True)
class StoredBackup:
    name: str
    moment: datetime.datetime
    verification: str = UNKNOWN


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def server_keep(keep) -> int:
    try:
        count = int(keep)
    except (TypeError, ValueError):
        count = 0
    if not 1 <= count <= MAXIMUM_KEEP:
        raise ConfigurationError(
            f"Keep between 1 and {MAXIMUM_KEEP} backups, not {keep}: the server keeps at "
            f"most {MAXIMUM_KEEP} backups in its backup folder."
        )
    return count


def is_future(name: str, now: datetime.datetime | None = None) -> bool:
    moment = parse_backup_moment(name)
    return moment is not None and moment > (now or utc_now())


def current_backup_names(
    names: Iterable[str], prefix: str | None = None, *, now: datetime.datetime | None = None
) -> list[str]:
    now = now or utc_now()
    return [
        name
        for name in sorted_backups(names, prefix)
        if not is_future(name, now)
    ]


def stale_stored_backups(backups: Iterable[StoredBackup], keep: int) -> list[str]:
    if keep < 1:
        raise ConfigurationError("Retention must keep at least one backup.")
    newest_first = sorted(backups, key=lambda backup: (backup.moment, backup.name), reverse=True)
    counted = [backup for backup in newest_first if backup.verification != FAILED]
    kept = {backup.name for backup in counted[:keep]}
    verified = next((b for b in newest_first if b.verification == PASSED), None)
    if verified is not None:
        kept.add(verified.name)
    stale = [
        backup
        for position, backup in enumerate(newest_first)
        if backup.name not in kept
        and (backup.verification != FAILED or position >= keep)
    ]
    return [backup.name for backup in reversed(stale)]


def stale_beyond_limit(
    backups: Iterable[StoredBackup], keep: int, protect: Iterable[str] = ()
) -> list[str]:
    backups = list(backups)
    newest_first = sorted(backups, key=lambda backup: (backup.moment, backup.name), reverse=True)
    verified = next((b.name for b in newest_first if b.verification == PASSED), None)
    protected = set(protect) | ({verified} if verified else set())
    stale = set(stale_stored_backups(backups, keep)) - protected
    remaining = [backup.name for backup in newest_first if backup.name not in stale]
    surplus = len(remaining) - keep
    for name in reversed(remaining):
        if surplus <= 0:
            break
        if name not in protected:
            stale.add(name)
            surplus -= 1
    return [backup.name for backup in reversed(newest_first) if backup.name in stale]


def remove_backups(directory: str, names: Iterable[str]) -> list[str]:
    removed = []
    for name in names:
        try:
            os.remove(os.path.join(directory, name))
        except OSError as exc:
            logger.warning("retention could not remove %s: %s", name, exc)
            continue
        removed.append(name)
    if removed:
        logger.info("retention removed %d backups in %s", len(removed), directory)
    return removed


def read_created(path: str) -> tuple[bool, datetime.datetime | None]:
    from .container.format import first_verified_header

    try:
        with open(path, "rb") as fh:
            found = first_verified_header(fh)
    except (OSError, ContainerError):
        return False, None
    if found is None:
        return False, None
    try:
        created = datetime.datetime.fromisoformat(found.manifest["created"])
    except (KeyError, TypeError, ValueError):
        return True, None
    if created.tzinfo is None:
        created = created.replace(tzinfo=datetime.timezone.utc)
    return True, created.astimezone(datetime.timezone.utc)


def is_leftover(name: str, size: int) -> bool:
    if _LEFTOVER_PATTERN.match(name):
        return True
    return size == 0 and is_backup_name(name)


def sweep_leftovers(
    directory: str,
    older_than: float = LEFTOVER_SECONDS,
    *,
    now: float | None = None,
) -> list[str]:
    now = time.time() if now is None else now
    try:
        entries = list(os.scandir(directory))
    except OSError as exc:
        logger.warning("could not look for leftover files in %s: %s", directory, exc)
        return []
    removed = []
    for entry in entries:
        try:
            if not entry.is_file(follow_symlinks=False):
                continue
            stat = entry.stat(follow_symlinks=False)
            if now - stat.st_mtime < older_than or not is_leftover(entry.name, stat.st_size):
                continue
            os.remove(entry.path)
        except OSError as exc:
            logger.warning("could not remove the leftover %s: %s", entry.name, exc)
            continue
        removed.append(entry.name)
    if removed:
        logger.info("removed %d leftover files in %s", len(removed), directory)
    return removed
