from __future__ import annotations

from typing import Any
from uuid import UUID

from dbs.manager.adapters import AdapterError
from dbs.manager.applications.models import Application
from dbs.manager.applications.services import ApplicationService
from dbs.manager.servers.models import Server
from dbs.manager.servers.services import ServerService


def identifier(value: str, what: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise AdapterError(f"{value!r} is not a {what} id.") from None


def number(value: str, what: str) -> int:
    if not value.isdigit():
        raise AdapterError(f"{value!r} is not a {what} number.")
    return int(value)


def server(user: Any, reference: str) -> Server:
    service = ServerService(user)
    try:
        return service.get(UUID(reference))
    except ValueError:
        pass
    found = service.list().filter(name=reference).first()
    if found is None:
        raise AdapterError(f"there is no server named {reference!r}.")
    return found


def servers(user: Any, references: list[str], every: bool) -> list[Server]:
    if every and references:
        raise AdapterError("name servers or choose all of them, not both.")
    if every:
        chosen = list(ServerService(user).list().order_by("name"))
        if not chosen:
            raise AdapterError("there are no servers yet.")
        return chosen
    if not references:
        raise AdapterError("name at least one server, or choose all of them.")
    return list(
        {
            found.pk: found for found in (server(user, ref) for ref in references)
        }.values()
    )


def application(user: Any, reference: str) -> Application:
    service = ApplicationService(user)
    try:
        return service.get(UUID(reference))
    except ValueError:
        pass
    found = service.list().filter(name=reference).first()
    if found is None:
        raise AdapterError(f"there is no application named {reference!r}.")
    return found


def applications(user: Any, references: list[str], every: bool) -> list[Application]:
    if every and references:
        raise AdapterError("name applications or choose all of them, not both.")
    if every:
        chosen = list(ApplicationService(user).list())
        if not chosen:
            raise AdapterError("there are no applications yet.")
        return chosen
    if not references:
        raise AdapterError("name at least one application, or choose all of them.")
    return list(
        {
            found.pk: found
            for found in (application(user, ref) for ref in references)
        }.values()
    )
