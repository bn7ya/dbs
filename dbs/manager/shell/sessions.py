from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import dataclass
from typing import Any

from dbs.manager.shell.buffer import OutputBuffer
from dbs.manager.shell.exceptions import TerminalClosed, TooManyTerminals

BUFFER_BYTES = 1024 * 1024
READ_CHUNK = 32 * 1024
INPUT_TIMEOUT = 10.0
MAX_SESSIONS = 4
MAX_PER_ACCOUNT = 2
MAX_WAITERS = 6
IDLE_SECONDS = 900
UNPOLLED_SECONDS = 60
LIFETIME_SECONDS = 7200
REMEMBERED_SECONDS = 60
CONNECTION_ERRORS = (OSError, EOFError)


class Reason:
    EXITED = "exited"
    CLOSED = "closed"
    IDLE = "idle"
    UNPOLLED = "unpolled"
    LIFETIME = "lifetime"
    REVOKED = "revoked"
    SIGNED_OUT = "signed_out"
    LOST = "lost"
    STOPPED = "stopped"


@dataclass(frozen=True)
class Owner:
    user_id: Any
    session_key: str
    password: str
    role: str | None


@dataclass(frozen=True)
class Ending:
    user_id: Any
    session_key: str
    cursor: int
    reason: str
    exit_status: int | None
    at: float


@dataclass(frozen=True)
class Place:
    mode: str
    server_id: str
    application_id: str
    label: str
    container: str


class ShellSession:
    def __init__(
        self,
        *,
        identifier: str,
        owner: Owner,
        place: Place,
        cols: int,
        rows: int,
        connection: ExitStack,
        channel: Any,
        activity_id: int,
        started: dict[str, Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.id = identifier
        self.owner = owner
        self.place = place
        self.cols = cols
        self.rows = rows
        self.connection = connection
        self.channel = channel
        self.activity_id = activity_id
        self.started = dict(started or {})
        self.clock = clock
        self.buffer = OutputBuffer(BUFFER_BYTES)
        self.lock = threading.Lock()
        self.opened_at = clock()
        self.last_input_at = self.opened_at
        self.last_poll_at = self.opened_at
        self.bytes_in = 0
        self.bytes_out = 0
        self.last_seq = -1
        self.waiting = False
        self.ended = threading.Event()
        self.reason = ""
        self.exit_status: int | None = None
        self.finished = False
        self.finishing = threading.Lock()
        self.reader = threading.Thread(
            target=self._read, name=f"dbs-terminal-{identifier[:8]}", daemon=True
        )

    def start(self) -> None:
        self.reader.start()

    @property
    def closed(self) -> bool:
        return self.ended.is_set()

    def write(self, seq: int, data: bytes) -> bool:
        with self.lock:
            if self.closed:
                raise TerminalClosed()
            if seq <= self.last_seq:
                return False
            try:
                self.channel.settimeout(INPUT_TIMEOUT)
                self.channel.sendall(data)
            except CONNECTION_ERRORS:
                self.end(Reason.LOST)
                raise TerminalClosed() from None
            self.last_seq = seq
            self.bytes_in += len(data)
            self.last_input_at = self.clock()
            return True

    def resize(self, cols: int, rows: int) -> None:
        with self.lock:
            if self.closed:
                raise TerminalClosed()
            with suppress(*CONNECTION_ERRORS):
                self.channel.resize_pty(width=cols, height=rows)
            self.cols, self.rows = cols, rows

    def read(self, cursor: int, wait: float) -> tuple[bytes, int, bool]:
        self.last_poll_at = self.clock()
        found = self.buffer.read(cursor, wait)
        self.last_poll_at = self.clock()
        return found

    def drained(self, cursor: int) -> bool:
        return self.closed and self.buffer.drained(cursor)

    def end(self, reason: str) -> None:
        if self.ended.is_set():
            return
        self.reason = reason
        self.ended.set()
        with suppress(Exception):
            self.channel.close()
        self.buffer.close()

    def release(self) -> None:
        with suppress(Exception):
            self.connection.close()

    def seconds(self) -> int:
        return int(self.clock() - self.opened_at)

    def overdue(self) -> str:
        now = self.clock()
        if now - self.opened_at >= LIFETIME_SECONDS:
            return Reason.LIFETIME
        if now - self.last_input_at >= IDLE_SECONDS:
            return Reason.IDLE
        if not self.waiting and now - self.last_poll_at >= UNPOLLED_SECONDS:
            return Reason.UNPOLLED
        return ""

    def summary(self) -> dict[str, Any]:
        return {
            "seconds": self.seconds(),
            "bytes_in": self.bytes_in,
            "bytes_out": self.bytes_out,
            "reason": self.reason,
            "exit_status": self.exit_status,
        }

    def _read(self) -> None:
        reason = Reason.EXITED
        try:
            while True:
                data = self.channel.recv(READ_CHUNK)
                if not data:
                    break
                self.bytes_out += len(data)
                if not self.buffer.append(data):
                    return
        except CONNECTION_ERRORS:
            reason = Reason.LOST
        with suppress(Exception):
            if self.channel.exit_status_ready():
                self.exit_status = self.channel.recv_exit_status()
        self.end(reason)


class Shells:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.sessions: dict[str, ShellSession] = {}
        self.endings: dict[str, Ending] = {}
        self.reserved: dict[Any, int] = {}
        self.waiters = 0
        self.lock = threading.Lock()

    @contextmanager
    def reserve(self, user_id: Any) -> Iterator[None]:
        with self.lock:
            open_now = [s for s in self.sessions.values() if not s.finished]
            mine = sum(1 for s in open_now if s.owner.user_id == user_id)
            pending = sum(self.reserved.values())
            if (
                len(open_now) + pending >= MAX_SESSIONS
                or mine + self.reserved.get(user_id, 0) >= MAX_PER_ACCOUNT
            ):
                raise TooManyTerminals()
            self.reserved[user_id] = self.reserved.get(user_id, 0) + 1
        try:
            yield
        finally:
            with self.lock:
                self.reserved[user_id] -= 1
                if not self.reserved[user_id]:
                    del self.reserved[user_id]

    def add(self, session: ShellSession) -> None:
        with self.lock:
            self.sessions[session.id] = session

    def find(self, identifier: str) -> ShellSession | None:
        with self.lock:
            return self.sessions.get(identifier)

    def owned_by(self, user_id: Any) -> list[ShellSession]:
        with self.lock:
            return [
                session
                for session in self.sessions.values()
                if session.owner.user_id == user_id and not session.finished
            ]

    def every(self) -> list[ShellSession]:
        with self.lock:
            return list(self.sessions.values())

    def forget(self, session: ShellSession) -> None:
        now = self.clock()
        with self.lock:
            self.sessions.pop(session.id, None)
            self.endings = {
                identifier: ending
                for identifier, ending in self.endings.items()
                if now - ending.at < REMEMBERED_SECONDS
            }
            self.endings[session.id] = Ending(
                session.owner.user_id,
                session.owner.session_key,
                session.buffer.end,
                session.reason,
                session.exit_status,
                now,
            )

    def ending(self, identifier: str) -> Ending | None:
        with self.lock:
            found = self.endings.get(identifier)
        if found is None or self.clock() - found.at >= REMEMBERED_SECONDS:
            return None
        return found

    @contextmanager
    def waiting(self, session: ShellSession) -> Iterator[bool]:
        with self.lock:
            allowed = not session.waiting and self.waiters < MAX_WAITERS
            if allowed:
                session.waiting = True
                self.waiters += 1
        try:
            yield allowed
        finally:
            if allowed:
                with self.lock:
                    session.waiting = False
                    self.waiters -= 1


SHELLS = Shells()
