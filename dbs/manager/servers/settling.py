from __future__ import annotations

import math
from datetime import datetime
from uuid import UUID

from django.core.cache import cache
from django.utils import timezone


def _key(subject_id: UUID) -> str:
    return f"settling:{subject_id}"


def mark(subject_id: UUID, until: datetime) -> None:
    seconds = (until - timezone.now()).total_seconds()
    if seconds <= 0:
        return
    current = settling_until(subject_id)
    if current is not None and current >= until:
        return
    cache.set(_key(subject_id), until, timeout=math.ceil(seconds))


def settling_until(subject_id: UUID) -> datetime | None:
    until = cache.get(_key(subject_id))
    if until is None or until <= timezone.now():
        return None
    return until
