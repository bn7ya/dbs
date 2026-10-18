from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from django.utils import timezone

from dbs.manager.activity import heartbeat
from dbs.manager.terminal.output import Output
from dbs.manager.terminal.session import TerminalSession

EVERY = 30.0
UNITS = ("bytes", "KB", "MB", "GB", "TB")


@contextmanager
def reported(session: TerminalSession, every: float = EVERY) -> Iterator[None]:
    if session.out.as_json or not session.waits:
        yield
        return
    stopped = threading.Event()
    reporter = threading.Thread(
        target=_report,
        args=(session.out, stopped, every),
        name="dbs-manager-progress",
        daemon=True,
    )
    reporter.start()
    try:
        yield
    finally:
        stopped.set()
        reporter.join(every)


def _report(out: Output, stopped: threading.Event, every: float) -> None:
    while not stopped.wait(every):
        for pulse in heartbeat.running():
            out.line(f"  {line(pulse.beat())}")


def line(beat: heartbeat.Beat) -> str:
    moved = f"{size(beat.moved)} moved"
    if not beat.connected:
        return f"working here, {moved}"
    if beat.state() == heartbeat.ALIVE:
        return f"connection alive, {moved}"
    quiet = int((timezone.now() - beat.heard_at).total_seconds())
    return f"connection lost: nothing heard for {quiet} s, {moved}"


def size(count: int) -> str:
    value = float(count)
    for unit in UNITS[:-1]:
        if value < 1024:
            return f"{int(value)} {unit}" if unit == "bytes" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} {UNITS[-1]}"
