from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from rest_framework.exceptions import APIException

from dbs.manager.adapters import checks
from dbs.manager.adapters.problems import problem
from dbs.manager.servers.models import Server
from dbs.manager.servers.serializers import CheckedServerSerializer
from dbs.manager.servers.services import DiscoveryService, ServerService
from dbs.manager.servers.services.discovery_service import discovered_settings


@dataclass(frozen=True)
class Settled:
    server: Server
    found: dict[str, Any] | None
    error: str


@dataclass(frozen=True)
class Checked:
    name: str
    connection: str
    status: str
    remote_version: str | None
    problem: str
    result: dict[str, Any]

    @property
    def ok(self) -> bool:
        return self.status == Server.CheckStatus.OK


def settle(
    user: Any, server: Server, project: str | None, given: Iterable[str]
) -> Settled:
    try:
        found = DiscoveryService(user).discover(server.pk, project_dir=project)
    except APIException as exc:
        return Settled(server=server, found=None, error=problem(exc))
    kept = set(given)
    changes = {
        key: value
        for key, value in discovered_settings(found, chosen=bool(project)).items()
        if key not in kept
    }
    if changes:
        server = ServerService(user).update(server.pk, **changes)
    return Settled(server=server, found=found, error="")


def checked(user: Any, chosen: Iterable[Server]) -> list[Checked]:
    service = ServerService(user)
    results = []
    for server in chosen:
        try:
            done = service.checked(server.pk)
        except APIException as exc:
            results.append(
                Checked(
                    name=server.name,
                    connection=_connection(service.get(server.pk)),
                    status="failed",
                    remote_version=None,
                    problem=problem(exc),
                    result={
                        "id": str(server.pk),
                        "name": server.name,
                        "error": problem(exc),
                    },
                )
            )
            continue
        data = CheckedServerSerializer(done).data
        results.append(
            Checked(
                name=done.server.name,
                connection=_connection(done.server),
                status=done.server.last_check_status,
                remote_version=data.get("remote_version"),
                problem=checks.problem(done.server),
                result=data,
            )
        )
    return results


def connection_label(state: str, error: str) -> str:
    if state != Server.ConnectionState.OFFLINE or not error:
        return state
    return f"{state} ({error})"


def _connection(server: Server) -> str:
    return connection_label(server.connection_state, server.last_connection_error)
