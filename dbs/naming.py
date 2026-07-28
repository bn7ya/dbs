from __future__ import annotations

import datetime
import re
from typing import Iterable

BACKUP_SUFFIX = ".dbs"
DEFAULT_PREFIX = "backup"
TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S"

_NAME_PATTERN = re.compile(
    r"^(?P<prefix>.+)-(?P<stamp>\d{8}-\d{6})Z(?:-(?P<ordinal>\d+))?"
    + re.escape(BACKUP_SUFFIX)
    + r"$"
)


def backup_filename(
    prefix: str = DEFAULT_PREFIX,
    moment: datetime.datetime | None = None,
    ordinal: int = 1,
) -> str:
    moment = moment or datetime.datetime.now(datetime.timezone.utc)
    stamp = moment.astimezone(datetime.timezone.utc).strftime(TIMESTAMP_FORMAT)
    suffix = "" if ordinal <= 1 else f"-{ordinal}"
    return f"{prefix}-{stamp}Z{suffix}{BACKUP_SUFFIX}"


def parse_backup_moment(name: str) -> datetime.datetime | None:
    match = _NAME_PATTERN.match(name)
    if not match:
        return None
    try:
        parsed = datetime.datetime.strptime(match.group("stamp"), TIMESTAMP_FORMAT)
    except ValueError:
        return None
    return parsed.replace(tzinfo=datetime.timezone.utc)


def backup_prefix(name: str) -> str | None:
    match = _NAME_PATTERN.match(name)
    return match.group("prefix") if match else None


def is_backup_name(name: str, prefix: str | None = None) -> bool:
    if parse_backup_moment(name) is None:
        return False
    return prefix is None or backup_prefix(name) == prefix


def sorted_backups(names: Iterable[str], prefix: str | None = None) -> list[str]:
    matching = [name for name in names if is_backup_name(name, prefix)]
    return sorted(matching, key=lambda name: (parse_backup_moment(name), name))
