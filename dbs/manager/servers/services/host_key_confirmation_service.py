from __future__ import annotations

import re
import secrets
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from django.core.cache import cache
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from dbs.manager.activity.services import ActivityService
from dbs.manager.servers.exceptions import (
    HostKeyConfirmationMismatch,
    HostKeyConfirmationMissing,
    HostKeyDecided,
    HostKeyNotConfirmed,
    HostKeyRejected,
)
from dbs.manager.servers.services.server_service import ServerService

if TYPE_CHECKING:
    from django.contrib.auth.models import AnonymousUser, User

CONFIRMATION_LIFETIME = timedelta(minutes=10)
ENTRY_PREFIX = "servers:host-key-confirmation:"
INDEX = "servers:host-key-confirmations"
ID_BYTES = 4
ID_PATTERN = re.compile(rf"[0-9a-f]{{{ID_BYTES * 2}}}")


class Action:
    CONFIRM = "server.host_key_confirm"
    REJECT = "server.host_key_reject"


class Decision:
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


@dataclass(frozen=True)
class HostKeyConfirmation:
    id: str
    host: str
    port: int
    key_type: str
    line: str
    fingerprint: str
    status: str
    requested_at: datetime
    expires_at: datetime

    @property
    def address(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{host}:{self.port}"


class HostKeyConfirmationService:
    def __init__(self, user: User | AnonymousUser | None) -> None:
        self.user: User | AnonymousUser | None = user
        self.servers = ServerService(user)
        self.activity = ActivityService(user)

    def request(self, host: str, port: int) -> HostKeyConfirmation:
        offered = self.servers.fingerprint(host, port)
        now = timezone.now()
        confirmation = HostKeyConfirmation(
            id=_new_id(),
            host=host,
            port=port,
            key_type=offered.key_type,
            line=offered.line,
            fingerprint=offered.fingerprint,
            status=Decision.PENDING,
            requested_at=now,
            expires_at=now + CONFIRMATION_LIFETIME,
        )
        _store(confirmation)
        cache.set(
            INDEX,
            [*_live_ids(), confirmation.id],
            timeout=int(CONFIRMATION_LIFETIME.total_seconds()),
        )
        return confirmation

    def pending(self) -> list[HostKeyConfirmation]:
        return sorted(
            (
                confirmation
                for confirmation in _held(_live_ids())
                if confirmation.status == Decision.PENDING
            ),
            key=lambda confirmation: confirmation.requested_at,
        )

    def get(self, confirmation_id: str) -> HostKeyConfirmation:
        held = _held([confirmation_id]) if ID_PATTERN.fullmatch(confirmation_id) else []
        if not held:
            raise HostKeyConfirmationMissing()
        return held[0]

    def confirm(self, confirmation_id: str) -> HostKeyConfirmation:
        return self._decide(confirmation_id, Decision.CONFIRMED, Action.CONFIRM)

    def reject(self, confirmation_id: str) -> HostKeyConfirmation:
        return self._decide(confirmation_id, Decision.REJECTED, Action.REJECT)

    def approved(self, confirmation_id: str, host: str, port: int) -> str:
        confirmation = self.get(confirmation_id)
        if (confirmation.host, confirmation.port) != (host, port):
            raise HostKeyConfirmationMismatch()
        if confirmation.status == Decision.REJECTED:
            raise HostKeyRejected()
        if confirmation.status != Decision.CONFIRMED:
            raise HostKeyNotConfirmed()
        return confirmation.line

    def settle(self, confirmation_id: str) -> None:
        cache.delete(ENTRY_PREFIX + confirmation_id)

    def _decide(
        self, confirmation_id: str, status: str, action: str
    ) -> HostKeyConfirmation:
        confirmation = self.get(confirmation_id)
        with self.activity.track(action, target=confirmation.address) as entry:
            entry.detail = {"fingerprint": confirmation.fingerprint}
            if confirmation.status != Decision.PENDING:
                raise HostKeyDecided()
            decided = replace(confirmation, status=status)
            _store(decided)
        return decided


def _new_id() -> str:
    while True:
        candidate = secrets.token_hex(ID_BYTES)
        if cache.get(ENTRY_PREFIX + candidate) is None:
            return candidate


def _store(confirmation: HostKeyConfirmation) -> None:
    remaining = (confirmation.expires_at - timezone.now()).total_seconds()
    cache.set(
        ENTRY_PREFIX + confirmation.id,
        {
            **asdict(confirmation),
            "requested_at": confirmation.requested_at.isoformat(),
            "expires_at": confirmation.expires_at.isoformat(),
        },
        timeout=max(int(remaining), 1),
    )


def _held(confirmation_ids: list[str]) -> list[HostKeyConfirmation]:
    found = cache.get_many([ENTRY_PREFIX + each for each in confirmation_ids])
    now = timezone.now()
    held = [
        _loaded(found[ENTRY_PREFIX + each])
        for each in confirmation_ids
        if ENTRY_PREFIX + each in found
    ]
    return [confirmation for confirmation in held if confirmation.expires_at > now]


def _live_ids() -> list[str]:
    return [confirmation.id for confirmation in _held(cache.get(INDEX) or [])]


def _loaded(stored: dict[str, Any]) -> HostKeyConfirmation:
    return HostKeyConfirmation(
        **{
            **stored,
            "requested_at": parse_datetime(stored["requested_at"]),
            "expires_at": parse_datetime(stored["expires_at"]),
        }
    )
