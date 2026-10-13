from __future__ import annotations

from typing import Any

from rest_framework.exceptions import APIException

from dbs import audit
from dbs.manager.activity.serializers import ActivitySerializer
from dbs.manager.activity.services import ActivityService
from dbs.manager.servers.exceptions import DbsTooOld
from dbs.models import AuditEvent


def finished(user: Any, job: AuditEvent) -> AuditEvent:
    return ActivityService(user).get(job.pk)


def described(user: Any, entry: AuditEvent) -> dict[str, Any]:
    servers = ActivityService(user).servers_for([entry])
    return ActivitySerializer(entry, context={"servers": servers}).data


def succeeded(entry: AuditEvent) -> bool:
    return entry.status == audit.SUCCEEDED


def failure(entry: AuditEvent) -> str:
    detail = entry.data if isinstance(entry.data, dict) else {}
    output = detail.get("output")
    if entry.error_code == DbsTooOld.default_code and detail.get("needs"):
        message = DbsTooOld.needing(str(detail["needs"]))
    else:
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
