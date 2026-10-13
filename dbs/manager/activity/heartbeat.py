from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.utils import timezone

ALIVE = "alive"
LOST = "lost"

_current: ContextVar[Pulse | None] = ContextVar("dbs_manager_pulse", default=None)
_running: dict[int, Pulse] = {}
_running_lock = threading.Lock()


def lost_after() -> timedelta:
    return timedelta(seconds=3 * settings.SSH_KEEPALIVE_INTERVAL)


@dataclass(frozen=True)
class Beat:
    connected: bool
    heard_at: datetime
    moved: int

    def state(self, now: datetime | None = None) -> str:
        quiet = (now or timezone.now()) - self.heard_at
        return ALIVE if quiet <= lost_after() else LOST


class Pulse:
    def __init__(self, activity_id: int) -> None:
        self.activity_id = activity_id
        self.lock = threading.Lock()
        self.moved = 0
        self.connections = 0
        self.heard_at = timezone.now()

    def __call__(self, moved: int = 0) -> None:
        with self.lock:
            self.moved += moved
            self.heard_at = timezone.now()

    @contextmanager
    def connected(self) -> Iterator[None]:
        with self.lock:
            self.connections += 1
            self.heard_at = timezone.now()
        try:
            yield
        finally:
            with self.lock:
                self.connections -= 1

    def beat(self) -> Beat:
        with self.lock:
            return Beat(
                connected=self.connections > 0, heard_at=self.heard_at, moved=self.moved
            )


def begin(activity_id: int) -> Pulse:
    pulse = Pulse(activity_id)
    with _running_lock:
        _running[activity_id] = pulse
    _current.set(pulse)
    return pulse


def end(activity_id: int) -> None:
    with _running_lock:
        _running.pop(activity_id, None)
    current = _current.get()
    if current is not None and current.activity_id == activity_id:
        _current.set(None)


def current() -> Pulse | None:
    return _current.get()


def running() -> list[Pulse]:
    with _running_lock:
        return list(_running.values())


def connection_of(activity_id: int) -> dict[str, Any] | None:
    with _running_lock:
        pulse = _running.get(activity_id)
    if pulse is None:
        return None
    beat = pulse.beat()
    if not beat.connected:
        return None
    return {"state": beat.state(), "last_activity_at": beat.heard_at, "bytes": beat.moved}
