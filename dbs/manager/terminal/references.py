from __future__ import annotations

from typing import Any
from uuid import UUID

from dbs.manager.servers.models import Server
from dbs.manager.servers.services import ServerService
from dbs.manager.terminal import CommandFailed


def identifier(value: str, what: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise CommandFailed(f"{value!r} is not a {what} id.") from None


def number(value: str, what: str) -> int:
    if not value.isdigit():
        raise CommandFailed(f"{value!r} is not a {what} number.")
    return int(value)


def server(user: Any, reference: str) -> Server:
    service = ServerService(user)
    try:
        return service.get(UUID(reference))
    except ValueError:
        pass
    found = service.list().filter(name=reference).first()
    if found is None:
        raise CommandFailed(
            f"there is no server named {reference!r}. django_dbs server list shows them."
        )
    return found


def servers(user: Any, references: list[str], every: bool) -> list[Server]:
    if every and references:
        raise CommandFailed("name servers or pass --all, not both.")
    if every:
        chosen = list(ServerService(user).list().order_by("name"))
        if not chosen:
            raise CommandFailed(
                "there are no servers yet. Add one with: django_dbs server add"
            )
        return chosen
    if not references:
        raise CommandFailed("name at least one server, or pass --all.")
    return list(
        {
            found.pk: found for found in (server(user, ref) for ref in references)
        }.values()
    )
