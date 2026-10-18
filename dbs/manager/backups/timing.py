from __future__ import annotations

import re
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone

DAY_MINUTES = 24 * 60
FARTHEST_AHEAD = timedelta(days=366)
ZONE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_+-]*(/[A-Za-z0-9_+-]+){0,2}$")
UTC_NAME = "UTC"


def zone(name: str) -> ZoneInfo | None:
    if not ZONE_NAME.match(name or ""):
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def next_on_grid(
    anchor: datetime, interval_minutes: int, zone_name: str, after: datetime
) -> datetime:
    if anchor > after:
        return anchor
    if interval_minutes % DAY_MINUTES == 0:
        local = zone(zone_name) or ZoneInfo(UTC_NAME)
        start = anchor.astimezone(local)
        days = interval_minutes // DAY_MINUTES
        elapsed = (after.astimezone(local).date() - start.date()).days
        step = max(elapsed // days, 0)
        while True:
            day = start.date() + timedelta(days=step * days)
            candidate = datetime.combine(day, start.time(), tzinfo=local)
            if candidate > after:
                return candidate.astimezone(dt_timezone.utc)
            step += 1
    interval = timedelta(minutes=interval_minutes)
    return anchor + ((after - anchor) // interval + 1) * interval


def planned(
    interval_minutes: int | None,
    enabled: bool,
    zone_name: str,
    anchor: datetime | None,
) -> dict[str, Any]:
    if interval_minutes is None:
        return {"anchor_at": anchor, "next_run_at": None}
    now = timezone.now()
    anchor = anchor or now + timedelta(minutes=interval_minutes)
    following = next_on_grid(anchor, interval_minutes, zone_name, now) if enabled else None
    return {"anchor_at": anchor, "next_run_at": following}


def within_reach(moment: datetime) -> bool:
    now = timezone.now()
    return now < moment <= now + FARTHEST_AHEAD
