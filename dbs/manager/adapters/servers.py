from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from rest_framework.exceptions import APIException

from dbs.manager.adapters import checks
from dbs.manager.adapters.problems import problem
from dbs.manager.servers.models import Server
from dbs.manager.servers.serializers import ServerSerializer
from dbs.manager.servers.services import ServerService


@dataclass(frozen=True)
class CheckedServer:
    name: str
    connection: str
    status: str
    engines: str
    problem: str
    result: dict[str, Any]

    @property
    def ok(self) -> bool:
        return self.status == Server.CheckStatus.OK


def checked(user: Any, chosen: Iterable[Server]) -> list[CheckedServer]:
    service = ServerService(user)
    results = []
    for server in chosen:
        try:
            done = service.check(server.pk)
        except APIException as exc:
            results.append(
                CheckedServer(
                    name=server.name,
                    connection=connection_of(service.get(server.pk)),
                    status=Server.CheckStatus.FAILED,
                    engines="-",
                    problem=problem(exc),
                    result={
                        "id": str(server.pk),
                        "name": server.name,
                        "error": problem(exc),
                    },
                )
            )
            continue
        results.append(
            CheckedServer(
                name=done.name,
                connection=connection_of(done),
                status=done.last_check_status,
                engines=checks.engines_label(done.engines),
                problem=checks.server_problem(done),
                result=ServerSerializer(done).data,
            )
        )
    return results


def connection_label(state: str, error: str) -> str:
    if state != Server.ConnectionState.OFFLINE or not error:
        return state
    return f"{state} ({error})"


def connection_of(server: Server) -> str:
    return connection_label(server.connection_state, server.last_connection_error)
