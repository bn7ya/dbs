from __future__ import annotations

from typing import Any

from dbs.manager.backups.serializers import (
    BackupPlanSerializer,
    PlanCreateSerializer,
    PlanUpdateSerializer,
)
from dbs.manager.backups.services import BackupPlanService
from dbs.manager.servers.services import ServerService
from dbs.manager.terminal import CommandFailed, jobs, references
from dbs.manager.terminal.forms import validated
from dbs.manager.terminal.session import TerminalSession

LIST_COLUMNS = (
    ("NAME", "name"),
    ("KIND", "kind"),
    ("EVERY", lambda row: _every(row["interval_minutes"])),
    ("KEEP", "keep"),
    ("ENABLED", "enabled"),
    ("NEXT RUN", "next_run_at"),
    ("LAST", "last_status"),
    ("ID", "id"),
)
SHOWN_FIELDS = (
    "id",
    "name",
    "kind",
    "paths",
    "pattern",
    "interval_minutes",
    "keep",
    "keep_remote",
    "enabled",
    "next_run_at",
    "last_run_at",
    "last_status",
    "last_error_code",
)
FIELDS = ("paths", "pattern", "interval_minutes", "keep", "keep_remote")


def list_plans(session: TerminalSession) -> int:
    service = BackupPlanService(session.user)
    if session.args.server:
        chosen = [references.server(session.user, session.args.server)]
    else:
        chosen = list(ServerService(session.user).list().order_by("name"))
    rows = [
        {**row, "server_name": server.name}
        for server in chosen
        for row in BackupPlanSerializer(service.list(server.pk), many=True).data
    ]
    columns = (("SERVER", "server_name"), *LIST_COLUMNS)
    session.out.table(rows, columns, empty="No plans yet.")
    return 0


def show(session: TerminalSession) -> int:
    plan = BackupPlanService(session.user).get(_plan_id(session))
    session.out.fields(BackupPlanSerializer(plan).data, SHOWN_FIELDS)
    return 0


def add(session: TerminalSession) -> int:
    args = session.args
    server = references.server(session.user, args.server)
    body = {
        "server": server.pk,
        "name": args.name,
        "kind": args.kind,
        "enabled": not args.disabled,
        **_fields(args),
    }
    data = validated(PlanCreateSerializer, body)
    service = BackupPlanService(session.user)
    plan = session.guarded(
        lambda password: service.create(account_password=password, **data)
    )
    session.out.say(f"Added the plan {plan.name}.", BackupPlanSerializer(plan).data)
    return 0


def edit(session: TerminalSession) -> int:
    args = session.args
    plan_id = _plan_id(session)
    body = _fields(args)
    if args.name is not None:
        body["name"] = args.name
    if args.enabled is not None:
        body["enabled"] = args.enabled
    if not body:
        raise CommandFailed("nothing to change; pass at least one option.")
    data = validated(PlanUpdateSerializer, body, partial=True)
    service = BackupPlanService(session.user)
    plan = session.guarded(
        lambda password: service.update(plan_id, account_password=password, **data)
    )
    session.out.say(f"Saved the plan {plan.name}.", BackupPlanSerializer(plan).data)
    return 0


def remove(session: TerminalSession) -> int:
    plan_id = _plan_id(session)
    service = BackupPlanService(session.user)
    plan = service.get(plan_id)
    service.delete(plan_id)
    session.out.say(f"Removed the plan {plan.name}.", {"removed": str(plan_id)})
    return 0


def run(session: TerminalSession) -> int:
    service = BackupPlanService(session.user)
    plan = service.get(_plan_id(session))
    if not session.out.as_json:
        print(f"Running {plan.name}...", flush=True)
    entry = jobs.finished(session.user, service.run(plan.pk))
    return jobs.outcome(session, entry, f"Ran the plan {plan.name}.")


def _plan_id(session: TerminalSession) -> Any:
    return references.identifier(session.args.plan, "plan")


def _fields(args: Any) -> dict[str, Any]:
    fields = {
        name: getattr(args, name) for name in FIELDS if getattr(args, name) is not None
    }
    if args.manual:
        if "interval_minutes" in fields:
            raise CommandFailed("pass --every or --manual, not both.")
        fields["interval_minutes"] = None
    return fields


def _every(minutes: Any) -> str:
    return "manual" if minutes is None else f"{minutes} min"
