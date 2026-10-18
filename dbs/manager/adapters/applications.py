from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from rest_framework.exceptions import APIException

from dbs.manager.adapters import AdapterError, checks
from dbs.manager.adapters.forms import validated
from dbs.manager.adapters.problems import problem
from dbs.manager.adapters.servers import connection_of
from dbs.manager.applications.models import Application
from dbs.manager.applications.serializers import (
    ApplicationCreateSerializer,
    CheckedApplicationSerializer,
    DiscoverRequestSerializer,
)
from dbs.manager.applications.services import ApplicationService, DiscoveryService
from dbs.manager.applications.services.discovery_service import settings_of
from dbs.manager.servers.models import Server


@dataclass(frozen=True)
class Added:
    application: Application
    report: dict[str, Any]
    candidate: dict[str, Any]


@dataclass(frozen=True)
class CheckedApplication:
    name: str
    server: str
    connection: str
    status: str
    remote_version: str | None
    problem: str
    result: dict[str, Any]

    @property
    def ok(self) -> bool:
        return self.status == Application.CheckStatus.OK


def discover(
    user: Any, server: Server, folder: str, account_password: str = ""
) -> dict[str, Any]:
    fields = validated(
        DiscoverRequestSerializer,
        {"server": str(server.pk), "folder": folder, "account_password": account_password},
    )
    fields.pop("server")
    return DiscoveryService(user).discover(server.pk, **fields)


def add(
    user: Any,
    server: Server,
    report: dict[str, Any],
    *,
    name: str,
    choice: int = 1,
    given: dict[str, Any] | None = None,
) -> Added:
    candidates = report.get("candidates") or []
    if not candidates and report.get("listing") and not report.get("trusted"):
        raise AdapterError(
            f"{report['folder']} or its parent can be written by others, so nothing "
            "in it was run."
        )
    if not candidates:
        raise AdapterError(f"found no Django project in {report.get('folder')}.")
    if not 1 <= choice <= len(candidates):
        raise AdapterError(f"choose a candidate from 1 to {len(candidates)}.")
    candidate = candidates[choice - 1]
    body = {
        **settings_of(candidate, name),
        **(given or {}),
        "server": str(server.pk),
        "discovered": True,
    }
    fields = validated(ApplicationCreateSerializer, body)
    application = ApplicationService(user).create(**fields)
    return Added(application=application, report=report, candidate=candidate)


def checked(user: Any, chosen: Iterable[Application]) -> list[CheckedApplication]:
    service = ApplicationService(user)
    results = []
    for application in chosen:
        try:
            done = service.checked(application.pk)
        except APIException as exc:
            current = service.get(application.pk)
            results.append(
                CheckedApplication(
                    name=application.name,
                    server=current.server.name,
                    connection=connection_of(current.server),
                    status=Application.CheckStatus.FAILED,
                    remote_version=None,
                    problem=problem(exc),
                    result={
                        "id": str(application.pk),
                        "name": application.name,
                        "error": problem(exc),
                    },
                )
            )
            continue
        data = CheckedApplicationSerializer(done).data
        results.append(
            CheckedApplication(
                name=done.application.name,
                server=done.application.server.name,
                connection=connection_of(done.application.server),
                status=done.application.last_check_status,
                remote_version=data.get("remote_version"),
                problem=checks.problem(done.application),
                result=data,
            )
        )
    return results
