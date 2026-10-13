from __future__ import annotations

import math
from datetime import datetime
from uuid import UUID

from django.core.cache import cache
from django.utils import timezone


def _key(server_id: UUID) -> str:
    return f"servers:settling:{server_id}"


def mark(server_id: UUID, until: datetime) -> None:
    seconds = (until - timezone.now()).total_seconds()
    if seconds <= 0:
        return
    current = settling_until(server_id)
    if current is not None and current >= until:
        return
    cache.set(_key(server_id), until, timeout=math.ceil(seconds))


def settling_until(server_id: UUID) -> datetime | None:
    until = cache.get(_key(server_id))
    if until is None or until <= timezone.now():
        return None
    return until
