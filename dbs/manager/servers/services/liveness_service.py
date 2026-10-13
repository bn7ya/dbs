from __future__ import annotations

from django.utils import timezone

from dbs.manager.common.exceptions import error_code_of
from dbs.manager.servers.models import Server
from dbs.manager.servers.repositories import ServerRepository


class ServerLiveness:
    def __init__(self) -> None:
        self.servers = ServerRepository()

    def online(self, server: Server) -> None:
        self.servers.record_connection(
            server,
            state=Server.ConnectionState.ONLINE,
            error="",
            seen_at=timezone.now(),
        )

    def offline(self, server: Server, error: BaseException) -> None:
        self.servers.record_connection(
            server,
            state=Server.ConnectionState.OFFLINE,
            error=error_code_of(error),
        )
