from __future__ import annotations

import logging
import os
from typing import Iterable

from .exceptions import ConfigurationError
from .naming import sorted_backups

logger = logging.getLogger("dbs")


def stale_backups(
    names: Iterable[str], keep: int, prefix: str | None = None
) -> list[str]:
    if keep < 1:
        raise ConfigurationError("Retention must keep at least one backup.")
    ordered = sorted_backups(names, prefix)
    if len(ordered) <= keep:
        return []
    return ordered[: len(ordered) - keep]


def prune_directory(
    directory: str,
    keep: int,
    prefix: str | None = None,
    *,
    dry_run: bool = False,
) -> list[str]:
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    stale = stale_backups(names, keep, prefix)
    if dry_run:
        return stale
    removed = []
    for name in stale:
        try:
            os.remove(os.path.join(directory, name))
        except OSError as exc:
            logger.warning("retention could not remove %s: %s", name, exc)
            continue
        removed.append(name)
    if removed:
        logger.info("retention removed %d local backups in %s", len(removed), directory)
    return removed


def prune_remote(
    session,
    keep: int,
    prefix: str | None = None,
    *,
    dry_run: bool = False,
) -> list[str]:
    stale = stale_backups(session.names(), keep, prefix)
    if dry_run:
        return stale
    removed = []
    for name in stale:
        session.delete(name)
        removed.append(name)
    if removed:
        logger.info("retention removed %d remote backups", len(removed))
    return removed
