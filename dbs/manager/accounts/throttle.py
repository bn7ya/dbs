from __future__ import annotations

from collections.abc import Iterable

from django.conf import settings
from django.core.cache import cache

PREFIX = "accounts:failures:"


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
