from __future__ import annotations

import logging
import threading
from collections.abc import Mapping, Sequence
from typing import Any, Optional

from django.db import close_old_connections, connection
from rest_framework.exceptions import APIException

from dbs.manager.activity import heartbeat
from dbs.manager.adapters.problems import problem
from dbs.manager.conf import inline_jobs
from dbs.manager.terminal import CommandFailed
from dbs.manager.terminal.dispatch import handler_of
from dbs.manager.terminal.progress import line as progress_line
from dbs.models import AuditEvent

from . import commands, meanings
from .commands import Verb
from .results import Outcome, ResultScreen
from .session import MenuSession, Transcript

EVERY = 0.5
STOPPED = 130
REFUSED = 2
FAILED = 1
log = logging.getLogger("dbs.manager.menu")


def run(
    app: Any,
    verb: Verb,
    values: Mapping[str, Any],
    quiet: bool = False,
    title: str = "",
    answers: Optional[Mapping[str, str]] = None,
) -> Outcome:
    transcript = Transcript()
    try:
        args = commands.parsed(verb, values)
    except commands.Refused as refused:
        return Outcome(REFUSED, transcript, problem=str(refused))
    screen = None
    if not quiet:
        screen = ResultScreen(
            app,
            title or verb.name,
            transcript,
            commands.shown(app.program, verb, values),
            secret=verb.path in meanings.SHOWS_SECRET,
        )
        app.push(screen)
        app.draw()
    outcome = _handled(app, args, transcript, screen, answers)
    if screen is not None:
        screen.finish(outcome)
    return outcome


def _handled(
    app: Any,
    args: Any,
    transcript: Transcript,
    screen: Any,
    answers: Optional[Mapping[str, str]],
) -> Outcome:
    session = MenuSession(args, app.user, app, transcript, answers)
    watcher = Watcher(app, screen) if screen is not None and app.live else None
    if not connection.in_atomic_block:
        close_old_connections()
    app.running = True
    try:
        if watcher is not None:
            watcher.start()
        with app.terminal.interruptible(), inline_jobs():
            code = handler_of(args)(session) or 0
        outcome = Outcome(code, transcript, args=args)
    except CommandFailed as failed:
        outcome = Outcome(FAILED, transcript, problem=str(failed), args=args)
    except APIException as refused:
        outcome = Outcome(FAILED, transcript, problem=problem(refused), args=args)
    except KeyboardInterrupt:
        outcome = Outcome(STOPPED, transcript, stopped=True, args=args)
    except Exception as broken:
        log.exception("a menu command failed")
        outcome = Outcome(
            FAILED, transcript, problem=f"{type(broken).__name__}: {broken}", args=args
        )
    finally:
        app.running = False
        if watcher is not None:
            watcher.stop()
    written = app.written()
    if written.strip():
        transcript.write(written.rstrip("\n"))
    return outcome


class Watcher(threading.Thread):
    def __init__(self, app: Any, screen: ResultScreen) -> None:
        super().__init__(name="dbs-manager-menu-progress", daemon=True)
        self.app = app
        self.screen = screen
        self.stopped = threading.Event()
        self.failed = False

    def run(self) -> None:
        try:
            while not self.stopped.wait(EVERY):
                self.screen.progress = self.read()
                self.app.draw()
        finally:
            connection.close()

    def read(self) -> Sequence[str]:
        try:
            return progress()
        except Exception:
            if not self.failed:
                log.exception("the menu could not read a job's progress")
            self.failed = True
            return self.screen.progress

    def stop(self) -> None:
        self.stopped.set()
        self.join(2 * EVERY)


def progress() -> list[str]:
    lines = []
    for pulse in heartbeat.running():
        lines.append(_described(pulse))
    return lines


def _described(pulse: heartbeat.Pulse) -> str:
    entry = AuditEvent.objects.filter(pk=pulse.activity_id).first()
    parts = []
    if entry is not None:
        parts.append(entry.target_name or entry.action)
        step = _step(entry.data if isinstance(entry.data, dict) else {})
        if step:
            parts.append(step)
    parts.append(progress_line(pulse.beat()))
    return ", ".join(parts)


def _step(detail: Mapping[str, Any]) -> str:
    if detail.get("step"):
        return str(detail["step"])
    for step in detail.get("steps") or ():
        if isinstance(step, dict) and step.get("status") == "running":
            return str(step.get("step", ""))
    current = detail.get("current")
    return str(current) if current else ""
