from __future__ import annotations

import math
import time
from collections.abc import Iterable

from django.conf import settings
from django.core.cache import cache

PREFIX = "accounts:failures:"
BACKOFF_PREFIX = "accounts:backoff:"
KNOWN_PREFIX = "accounts:known:"
LARGEST_DOUBLING = 16


def _key(name: str) -> str:
    return PREFIX + name


def _count(key: str) -> int:
    cache.add(key, 0, timeout=settings.AUTH_FAILURE_WINDOW)
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=settings.AUTH_FAILURE_WINDOW)
        return 1


def counted(limits: Iterable[tuple[str, int]]) -> bool:
    counts = [(_count(_key(name)), limit) for name, limit in limits]
    return all(count <= limit for count, limit in counts)


def given_back(names: Iterable[str]) -> None:
    for name in names:
        try:
            cache.decr(_key(name))
        except ValueError:
            continue


def cleared(names: Iterable[str]) -> None:
    cache.delete_many([_key(name) for name in names])


def slowed(name: str, free: int) -> int:
    failures = _count(_key(name))
    if failures <= free:
        return 0
    doublings = min(failures - free - 1, LARGEST_DOUBLING)
    wait = min(
        settings.AUTH_BACKOFF_SECONDS * 2**doublings,
        settings.AUTH_BACKOFF_MAX_SECONDS,
    )
    cache.set(BACKOFF_PREFIX + name, time.time() + wait, timeout=math.ceil(wait))
    return wait


def waiting(name: str) -> int:
    until = cache.get(BACKOFF_PREFIX + name)
    if until is None:
        return 0
    return max(0, math.ceil(until - time.time()))


def remember(name: str, address: str) -> None:
    cache.set(
        KNOWN_PREFIX + f"{name}:{address}",
        True,
        timeout=settings.AUTH_KNOWN_ADDRESS_SECONDS,
    )


def known(name: str, address: str) -> bool:
    return bool(cache.get(KNOWN_PREFIX + f"{name}:{address}"))


def unslowed(name: str) -> None:
    cache.delete_many([_key(name), BACKOFF_PREFIX + name])
