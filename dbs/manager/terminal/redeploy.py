from __future__ import annotations

from typing import Any

from dbs.manager.activity.services import ActivityService
from dbs.manager.adapters import jobs, references
from dbs.manager.adapters.forms import validated
from dbs.manager.applications.models import Application
from dbs.manager.redeploy.serializers import RedeploySerializer, RevertSerializer
from dbs.manager.redeploy.services import RUN, RedeployService
from dbs.manager.terminal import CommandFailed
from dbs.manager.terminal.progress import reported
from dbs.manager.terminal.session import TerminalSession


def start(session: TerminalSession) -> int:
    args = session.args
    source = references.application(session.user, args.source)
    target = references.application(session.user, args.target)
    body: dict[str, Any] = {
        "source_application": source.pk,
        "target_application": target.pk,
        "flush": args.flush,
        "rehearsal": not args.real,
    }
    if args.backup:
        body["backup"] = references.identifier(args.backup, "backup")
    if args.env_version:
        body["env_version"] = references.identifier(args.env_version, "version")
    body.update(_confirmed(session, target))
    data = validated(RedeploySerializer, body)
    _say(session, f"Moving {source.name} onto {target.name}...")
    with reported(session):
        entry = jobs.finished(session.user, RedeployService(session.user).start(**data))
    _steps(session, entry)
    if not jobs.succeeded(entry) and (entry.data or {}).get("revertable"):
        _say(
            session,
            f"{target.name} can be put back as it was: "
            f"django_dbs redeploy revert {entry.pk} --real",
        )
    done = "Moved" if args.real else "Rehearsed moving"
    return session.outcome(entry, f"{done} {source.name} onto {target.name}.")


def revert(session: TerminalSession) -> int:
    args = session.args
    move = references.number(args.move, "move")
    found = ActivityService(session.user).get(move)
    if found.action != RUN:
        raise CommandFailed(f"{move} is not a move.")
    target = references.application(session.user, found.subject)
    body: dict[str, Any] = {"rehearsal": not args.real, **_confirmed(session, target)}
    data = validated(RevertSerializer, body)
    _say(session, f"Putting {target.name} back as it was before move {move}...")
    with reported(session):
        entry = jobs.finished(
            session.user, RedeployService(session.user).revert(move, **data)
        )
    _steps(session, entry)
    done = "Reverted" if args.real else "Rehearsed reverting"
    return session.outcome(entry, f"{done} {target.name}.")


def _confirmed(session: TerminalSession, target: Application) -> dict[str, str]:
    args = session.args
    if not args.real:
        return {}
    if not args.confirm_name:
        session.confirm(
            f"Type the target application's name ({target.name}) to go ahead:",
            expected=target.name,
        )
    return {
        "confirm_name": args.confirm_name or target.name,
        "password": session.password(),
    }


def _steps(session: TerminalSession, entry: Any) -> None:
    detail = entry.data or {}
    for step in detail.get("steps", []):
        _say(session, f"  {step['step']:<14} {step['status']}")
    if detail.get("failed_step"):
        _say(session, f"Stopped at {detail['failed_step']}.")


def _say(session: TerminalSession, message: str) -> None:
    if not session.out.as_json:
        print(message, flush=True)
