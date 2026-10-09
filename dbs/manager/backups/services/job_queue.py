from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from django.db import transaction

from dbs.manager.activity.services import ActivityService
from dbs.manager.backups.exceptions import BackupRunning
from dbs.manager.backups.locks import TakeLock
from dbs.models import AuditEvent

if TYPE_CHECKING:
    from django.contrib.auth.models import AnonymousUser, User

    from dbs.manager.servers.models import Server

Send = Callable[[AuditEvent], object]


class JobQueue:
    def __init__(self, user: User | AnonymousUser | None) -> None:
        self.activity = ActivityService(user)
        self.locks = TakeLock()

    def queue(
        self, action: str, *, server: Server, target: str, send: Send
    ) -> AuditEvent:
        with transaction.atomic():
            job = self.activity.queue(action, server=server, target=target)
            transaction.on_commit(lambda: self.send(job, send))
        return job

    def queue_backup(
        self,
        action: str,
        *,
        server: Server,
        target: str,
        send: Send,
        detail: dict[str, Any] | None = None,
    ) -> AuditEvent:
        with transaction.atomic():
            job = self.activity.queue(
                action, server=server, target=target, detail=detail
            )
            if not self.locks.acquire(server.pk, job.pk):
                raise BackupRunning()
            transaction.on_commit(
                lambda: self.send(
                    job, send, on_failure=lambda: self.locks.release(server.pk, job.pk)
                )
            )
        return job

    def send(
        self,
        job: AuditEvent,
        send: Send,
        *,
        on_failure: Callable[[], None] | None = None,
    ) -> None:
        try:
            send(job)
        except Exception as exc:
            self.activity.fail(job.pk, exc)
            if on_failure is not None:
                on_failure()
            raise
