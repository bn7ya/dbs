from __future__ import annotations

import logging
import re
import signal
import threading
import time
from typing import Callable

from .exceptions import ConfigurationError

logger = logging.getLogger("dbs")

_INTERVAL_PATTERN = re.compile(r"^(\d+)([smhd]?)$")

_MULTIPLIERS = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_interval(spec: str) -> int:
    match = _INTERVAL_PATTERN.match(str(spec).strip().lower())
    if not match:
        raise ConfigurationError(
            f"Cannot read the interval {spec!r}; use forms like 90s, 30m, 6h or 1d."
        )
    seconds = int(match.group(1)) * _MULTIPLIERS[match.group(2)]
    if seconds <= 0:
        raise ConfigurationError("The interval must be greater than zero.")
    return seconds


def install_stop_handlers(stop: threading.Event) -> None:
    def request_stop(signum, frame):
        logger.info("stop requested by signal %s", signum)
        stop.set()

    for name in ("SIGTERM", "SIGINT"):
        number = getattr(signal, name, None)
        if number is None:
            continue
        try:
            signal.signal(number, request_stop)
        except ValueError:
            continue


def run_schedule(
    action: Callable[[], None],
    interval_seconds: int,
    *,
    once: bool = False,
    stop: threading.Event | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    stop = stop or threading.Event()
    failures = 0
    while True:
        if stop.is_set():
            break
        started = clock()
        try:
            action()
        except Exception as exc:
            failures += 1
            logger.exception("scheduled backup cycle failed: %s", exc)
        if once:
            break
        remaining = interval_seconds - (clock() - started)
        if stop.wait(max(remaining, 0)):
            break
    return failures
