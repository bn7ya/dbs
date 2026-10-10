from __future__ import annotations

from typing import Any

from rest_framework.exceptions import APIException

from dbs import audit
from dbs.manager.activity.serializers import ActivitySerializer
from dbs.manager.activity.services import ActivityService
from dbs.manager.terminal import CommandFailed
from dbs.models import AuditEvent


def finished(user: Any, job: AuditEvent) -> AuditEvent:
    return ActivityService(user).get(job.pk)


def described(user: Any, entry: AuditEvent) -> dict[str, Any]:
    servers = ActivityService(user).servers_for([entry])
    return ActivitySerializer(entry, context={"servers": servers}).data


def succeeded(entry: AuditEvent) -> bool:
    return entry.status == audit.SUCCEEDED


def failure(entry: AuditEvent) -> str:
    detail = entry.data or {}
    output = detail.get("output") if isinstance(detail, dict) else None
    message = _messages().get(entry.error_code, entry.error_code)
    return " ".join(part for part in (message, output) if part) or entry.status


def _messages() -> dict[str, str]:
    found: dict[str, str] = {}
    waiting = list(APIException.__subclasses__())
    while waiting:
        kind = waiting.pop()
        waiting.extend(kind.__subclasses__())
        found.setdefault(kind.default_code, str(kind.default_detail))
    return found


def outcome(session: Any, entry: AuditEvent, done: str) -> int:
    if succeeded(entry):
        session.out.say(done, described(session.user, entry))
        return 0
    if session.out.as_json:
        session.out.json(described(session.user, entry))
        return 1
    raise CommandFailed(f"failed: {failure(entry)}")
