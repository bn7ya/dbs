from __future__ import annotations

from typing import TYPE_CHECKING

from dbs.manager.conf import backup_keep_max
from dbs.retention import MAXIMUM_KEEP, is_valid_maximum

if TYPE_CHECKING:
    from dbs.manager.applications.models import Application


def keep_max() -> int:
    return backup_keep_max()


def keep_remote_max(application: Application) -> int:
    reported = (application.last_check_report or {}).get("max_backups")
    return int(reported) if is_valid_maximum(reported) else MAXIMUM_KEEP
