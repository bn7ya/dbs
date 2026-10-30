from __future__ import annotations

from typing import Any

from dbs.manager.adapters import jobs, references
from dbs.manager.adapters.forms import validated
from dbs.manager.applications.services import ApplicationService
from dbs.manager.relocation.serializers import ServerMoveSerializer
from dbs.manager.relocation.services import RelocationService
from dbs.manager.servers.models import Server
from dbs.manager.terminal import CommandFailed
from dbs.manager.terminal.progress import reported
from dbs.manager.terminal.session import TerminalSession


def move(session: TerminalSession) -> int:
    args = session.args
    source = references.server(session.user, args.server)
    target = references.server(session.user, args.target)
    body: dict[str, Any] = {
        "target_server": target.pk,
        "applications": _choices(session, source),
        "rehearsal": not args.real,
    }
    if args.resume:
        body["resume_of"] = references.number(args.resume, "move")
    if args.real:
        body.update(_confirmed(session, source, target))
    data = validated(ServerMoveSerializer, body)
    _say(
        session,
        f"{'Moving' if args.real else 'Planning the move of'} {source.name} onto "
        f"{target.name}...",
    )
    with reported(session):
        entry = jobs.finished(
            session.user,
            RelocationService(session.user).start(source_server=source.pk, **data),
        )
    _report(session, entry)
    if args.real and not jobs.succeeded(entry):
        _say(
            session,
            f"Resume from where it stopped: django_dbs server move {source.name} "
            f"--to {target.name} --real --resume {entry.pk}",
        )
    done = "Moved" if args.real else "Planned the move of"
    return session.outcome(entry, f"{done} {source.name} onto {target.name}.")


def _choices(session: TerminalSession, source: Server) -> list[dict[str, Any]]:
    args = session.args
    names = _pairs(args.names or [], "=", "--name APP=NEW")
    skipped = _pairs(args.skip_volumes or [], ":", "--skip-volume APP:VOLUME", many=True)
    given = [item.partition("=") for item in args.apps or []]
    if given:
        chosen = [(references.application(session.user, name), folder) for name, _, folder in given]
    else:
        chosen = [
            (application, "")
            for application in ApplicationService(session.user).list(server=source.pk)
        ]
    for application, _ in chosen:
        if application.server_id != source.pk:
            raise CommandFailed(f"{application.name} does not run on {source.name}.")
    return [
        {
            "application": application.pk,
            "name": names.get(application.name, ""),
            "folder": folder,
            "skip_volumes": skipped.get(application.name, []),
            "copy_plans": not args.no_plans,
        }
        for application, folder in chosen
    ]


def _pairs(items: list[str], separator: str, usage: str, many: bool = False) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for item in items:
        key, divided, value = item.partition(separator)
        if not divided or not key or not value:
            raise CommandFailed(f"use {usage}.")
        if many:
            found.setdefault(key, []).append(value)
        else:
            found[key] = value
    return found


def _confirmed(session: TerminalSession, source: Server, target: Server) -> dict[str, str]:
    args = session.args
    if not args.confirm_name:
        session.confirm(
            f"Type the new server's name ({target.name}) to go ahead:",
            expected=target.name,
        )
    secrets = {
        "confirm_name": args.confirm_name or target.name,
        "password": session.password(),
    }
    if not args.no_sudo_password:
        secrets["sudo_password"] = session.secret(
            f"sudo password for {target.username} on {target.name}",
            from_stdin=getattr(args, "sudo_password_stdin", False),
            stdin_option="--sudo-password-stdin",
        )
    if args.source_sudo_password:
        secrets["source_sudo_password"] = session.secret(
            f"sudo password for {source.username} on {source.name}"
        )
    return secrets


def _report(session: TerminalSession, entry: Any) -> None:
    if session.out.as_json:
        return
    detail = entry.data or {}
    found = detail.get("inventory") or {}
    for plan in found.get("applications", []):
        folder = plan["folder"]
        size = _size(folder.get("bytes"))
        _say(session, f"{plan['name']} -> {plan['target_name']} in {folder.get('target') or '-'} ({size})")
        if plan["images"]:
            _say(session, f"  images   {', '.join(image['ref'] for image in plan['images'])}")
        volumes = [volume["name"] for volume in plan["volumes"] if volume["selected"]]
        if volumes:
            _say(session, f"  volumes  {', '.join(volumes)}")
        database = plan.get("database") or {}
        if database.get("vendor"):
            _say(session, f"  database {database['vendor']} ({database['placement']}): {database['action']}")
        for item in plan["notes"]:
            _say(session, f"  note     {item['code']}")
    packages = (found.get("packages") or {}).get("packages") or []
    if packages:
        _say(session, f"Installs on the new server: {' '.join(packages)}")
    for item in found.get("notes", []):
        _say(session, f"Note: {item['code']}")
    for item in detail.get("blockers", []):
        where = f"{item['application']}: " if item.get("application") else ""
        _say(session, f"Blocked: {where}{item['code']}")
    for phase in detail.get("phases", []):
        title = phase.get("name") or phase["phase"]
        _say(session, f"{title}")
        for step in phase["steps"]:
            key = f" {step['key']}" if step.get("key") else ""
            _say(session, f"  {step['step']:<16} {step['status']}{key}")
    if detail.get("leftovers"):
        _say(session, f"Left on the new server: {', '.join(detail['leftovers'])}")


def _size(value: int | None) -> str:
    if value is None:
        return "size unknown"
    for unit in ("bytes", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value} {unit}" if unit == "bytes" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _say(session: TerminalSession, message: str) -> None:
    if not session.out.as_json:
        session.out.line(message)
