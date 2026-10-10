from __future__ import annotations

from typing import Any

from dbs.manager.redeploy.serializers import RedeploySerializer
from dbs.manager.redeploy.services import RedeployService
from dbs.manager.terminal import jobs, references
from dbs.manager.terminal.forms import validated
from dbs.manager.terminal.session import TerminalSession


def start(session: TerminalSession) -> int:
    args = session.args
    source = references.server(session.user, args.source)
    target = references.server(session.user, args.target)
    body: dict[str, Any] = {
        "source_server": source.pk,
        "target_server": target.pk,
        "backup": references.identifier(args.backup, "backup"),
        "archives": [references.identifier(item, "archive") for item in args.archives],
        "migrate": args.migrate,
        "flush": args.flush,
        "rehearsal": not args.real,
    }
    if args.env_version:
        body["env_version"] = references.identifier(args.env_version, "version")
    if args.real:
        if not args.confirm_name:
            session.confirm(
                f"Type the target server's name ({target.name}) to go ahead:",
                expected=target.name,
            )
        body["confirm_name"] = args.confirm_name or target.name
        body["password"] = session.password()
    data = validated(RedeploySerializer, body)
    if not session.out.as_json:
        print(f"Redeploying {source.name} onto {target.name}...", flush=True)
    entry = jobs.finished(session.user, RedeployService(session.user).start(**data))
    if not session.out.as_json:
        for step in (entry.data or {}).get("steps", []):
            print(f"  {step['step']:<12} {step['status']}")
    done = "Redeployed" if args.real else "Rehearsed redeploying"
    return jobs.outcome(session, entry, f"{done} {source.name} onto {target.name}.")
