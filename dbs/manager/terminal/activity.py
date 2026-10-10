from __future__ import annotations

from dbs.manager.activity.serializers import (
    ActivityFilterSerializer,
    ActivitySerializer,
)
from dbs.manager.activity.services import ActivityService
from dbs.manager.terminal import CommandFailed, jobs, references
from dbs.manager.terminal.forms import validated
from dbs.manager.terminal.session import TerminalSession

LIST_COLUMNS = (
    ("#", "id"),
    ("WHEN", "created_at"),
    ("ACTION", "action"),
    ("STATUS", "status"),
    ("SERVER", "server_name"),
    ("TARGET", "target"),
    ("BY", "actor"),
    ("ERROR", "error_code"),
)
SHOWN_FIELDS = (
    "id",
    "action",
    "status",
    "server_name",
    "target",
    "actor",
    "ip",
    "error_code",
    "detail",
    "created_at",
    "started_at",
    "finished_at",
)


def list_activity(session: TerminalSession) -> int:
    args = session.args
    if args.limit < 1:
        raise CommandFailed("--limit must be at least 1.")
    body = {
        key: value
        for key, value in {"action": args.action, "status": args.status}.items()
        if value
    }
    if args.server:
        body["server"] = references.server(session.user, args.server).pk
    service = ActivityService(session.user)
    entries = list(
        service.list(**validated(ActivityFilterSerializer, body))[: args.limit]
    )
    servers = service.servers_for(entries)
    rows = ActivitySerializer(entries, many=True, context={"servers": servers}).data
    session.out.table(rows, LIST_COLUMNS, empty="Nothing has happened yet.")
    return 0


def show(session: TerminalSession) -> int:
    entry_id = references.number(session.args.entry, "activity")
    entry = ActivityService(session.user).get(entry_id)
    session.out.fields(jobs.described(session.user, entry), SHOWN_FIELDS)
    return 0
