from __future__ import annotations

from dbs.manager.envfiles.serializers import (
    EnvComparisonSerializer,
    EnvPulledSerializer,
    EnvPushedSerializer,
    EnvVersionSerializer,
)
from dbs.manager.envfiles.services import EnvFileService
from dbs.manager.terminal import references
from dbs.manager.terminal.output import text
from dbs.manager.terminal.session import TerminalSession

LIST_COLUMNS = (
    ("KEPT", "created_at"),
    ("SOURCE", "source"),
    ("SIZE", "size"),
    ("KEYS", lambda row: len(row["keys"])),
    ("BY", "taken_by"),
    ("ID", "id"),
)


def list_versions(session: TerminalSession) -> int:
    server = references.server(session.user, session.args.server)
    versions = EnvFileService(session.user).list(server.pk)
    rows = EnvVersionSerializer(versions, many=True).data
    session.out.table(rows, LIST_COLUMNS, empty=f"No versions kept for {server.name}.")
    return 0


def pull(session: TerminalSession) -> int:
    server = references.server(session.user, session.args.server)
    pulled = EnvFileService(session.user).pull(server.pk)
    message = (
        f"Kept a new version of {pulled.version.path}."
        if pulled.created
        else f"{pulled.version.path} has not changed since the last version."
    )
    session.out.say(message, EnvPulledSerializer(pulled).data)
    return 0


def compare(session: TerminalSession) -> int:
    first = references.identifier(session.args.version, "version")
    other = references.identifier(session.args.other, "version")
    comparison = EnvFileService(session.user).compare(first, other)
    data = EnvComparisonSerializer(comparison).data
    if session.out.as_json:
        session.out.json(data)
        return 0
    for title in ("added", "removed", "changed"):
        print(f"{title:<8} {text(data[title])}")
    return 0


def reveal(session: TerminalSession) -> int:
    version = references.identifier(session.args.version, "version")
    content = EnvFileService(session.user).reveal(version, session.password())
    if session.out.as_json:
        session.out.json({"content": content})
    else:
        print(content, end="" if content.endswith("\n") else "\n")
    return 0


def push(session: TerminalSession) -> int:
    version = references.identifier(session.args.version, "version")
    pushed = EnvFileService(session.user).push(version, session.password())
    session.out.say(
        f"Wrote it to {pushed.path}.", EnvPushedSerializer({"version": pushed}).data
    )
    return 0
