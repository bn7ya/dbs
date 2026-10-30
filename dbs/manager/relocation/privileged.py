from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import BinaryIO

from django.conf import settings
from django.views.decorators.debug import sensitive_variables

from dbs.manager.relocation import catalogue
from dbs.manager.relocation.catalogue import Command
from dbs.manager.relocation.exceptions import (
    PrivilegedCommandFailed,
    SudoMissing,
    SudoNeedsTty,
    SudoPasswordRequired,
    SudoPasswordWrong,
)
from dbs.manager.servers.exceptions import RemoteCommandFailed
from dbs.manager.servers.gateways import RemoteHost, Writable
from dbs.transports import RemoteResult

WRONG_PASSWORD = ("incorrect password", "sorry, try again", "authentication failure")
NEEDS_TTY = ("must have a tty", "no tty present")
NO_PASSWORD_ALLOWED = ("a password is required",)
OUTPUT_TAIL = 500


@dataclass(frozen=True)
class SudoPasswords:
    target: str = field(default="", repr=False)
    source: str = field(default="", repr=False)


def sudo_mode(remote: RemoteHost) -> str:
    found = _quiet_run(remote, catalogue.user_ids())
    if found is not None and found.ok and found.stdout.startswith("uid=0("):
        return catalogue.ROOT
    present = _quiet_run(remote, catalogue.sudo_present())
    if present is None or present.exit_status == 127:
        return catalogue.MISSING
    free = _quiet_run(remote, catalogue.sudo_without_password())
    return catalogue.NOPASSWD if free is not None and free.ok else catalogue.PASSWORD


def _quiet_run(remote: RemoteHost, command: Command) -> RemoteResult | None:
    try:
        return remote.run(list(command.argv), cwd=command.cwd, env=command.environment)
    except RemoteCommandFailed:
        return None


def scrubbed(text: str, secret: str) -> str:
    tail = text.strip()[-OUTPUT_TAIL:]
    return tail.replace(secret, "***") if secret else tail


class Privileged:
    @sensitive_variables("password")
    def __init__(self, remote: RemoteHost, mode: str, password: str = "") -> None:
        self.remote = remote
        self.mode = mode
        self._password = password
        self.verified = mode in (catalogue.ROOT, catalogue.NOPASSWD)

    @property
    def can_escalate(self) -> bool:
        return self.mode != catalogue.MISSING

    def argv(self, command: Command) -> list[str]:
        if command.root and self.mode == catalogue.MISSING:
            raise SudoMissing()
        return catalogue.privileged(command, self.mode)

    def _line(self, argv: list[str]) -> str | None:
        if not catalogue.needs_password_line(argv):
            return None
        if not self._password:
            raise SudoPasswordRequired()
        return self._password

    def verify(self) -> None:
        if self.verified:
            return
        if self.mode == catalogue.MISSING:
            raise SudoMissing()
        argv = self.argv(catalogue.sudo_check())
        result = self.remote.run(argv, stdin_line=self._line(argv))
        if not result.ok:
            raise refusal_of(result, self._password)
        self.verified = True

    def run(
        self,
        command: Command,
        *,
        timeout: float | None = None,
        check: bool = True,
    ) -> RemoteResult:
        argv = self.argv(command)
        if command.root:
            self.verify()
        result = self.remote.run(
            argv,
            cwd=command.cwd,
            env=command.environment,
            stdin_line=self._line(argv),
            timeout=timeout,
        )
        if check and not result.ok:
            raise refusal_of(result, self._password)
        return result

    def feed(
        self,
        command: Command,
        source: BinaryIO | bytes,
        *,
        timeout: float | None = None,
        check: bool = True,
    ) -> RemoteResult:
        argv = self.argv(command)
        if command.root:
            self.verify()
        stream = io.BytesIO(source) if isinstance(source, bytes) else source
        result = self.remote.feed(
            argv,
            stream,
            cwd=command.cwd,
            env=command.environment,
            timeout=timeout,
            stdin_line=self._line(argv),
        )
        if check and not result.ok:
            raise refusal_of(result, self._password)
        return result

    def stream(
        self,
        command: Command,
        sink: Writable,
        *,
        progress: Callable[[int], None] | None = None,
    ) -> RemoteResult:
        argv = self.argv(command)
        if command.root:
            self.verify()
        return self.remote.stream(
            argv,
            sink,
            cwd=command.cwd,
            env=command.environment,
            stdin_line=self._line(argv),
            timeout=settings.BACKUP_TOTAL_TIMEOUT,
            idle_timeout=settings.BACKUP_IDLE_TIMEOUT,
            progress=progress,
        )

    def stdin_for(self, command: Command) -> str | None:
        return self._line(self.argv(command))

    def scrub(self, text: str) -> str:
        return scrubbed(text, self._password)


def refusal_of(result: RemoteResult, secret: str) -> Exception:
    said = (result.stderr or result.stdout or "").lower()
    if any(phrase in said for phrase in NEEDS_TTY):
        return SudoNeedsTty()
    if any(phrase in said for phrase in WRONG_PASSWORD):
        return SudoPasswordWrong()
    if any(phrase in said for phrase in NO_PASSWORD_ALLOWED):
        return SudoPasswordRequired()
    return PrivilegedCommandFailed(output=scrubbed(result.stderr or result.stdout, secret))
