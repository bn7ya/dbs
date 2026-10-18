from __future__ import annotations

import shlex
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from rest_framework.exceptions import APIException, ErrorDetail, ValidationError

from dbs import audit
from dbs.manager.activity.services import ActivityService, collecting_jobs
from dbs.manager.adapters.problems import problem
from dbs.manager.common.exceptions import error_code_of
from dbs.manager.console.exceptions import ConsoleBusy, ConsoleStopped, PasswordNeeded
from dbs.manager.console.parser import PROG, parsed
from dbs.manager.console.session import CappedText, ConsoleSession
from dbs.manager.permissions import Capability, requires
from dbs.manager.terminal import CommandFailed
from dbs.manager.terminal.dispatch import handler_of

RUN = "console.command"
LINE_MAX = 2000
PROGRAM_NAMES = ("django_dbs", "django-dbs", "dbs")
HELP_WORDS = ("help", "?")
FAILED = 1
TOO_LONG = "Keep a command under 2,000 characters."
UNBALANCED = "Close every quote in the command."
REQUIRED = "Type a command, or help."


@dataclass
class ConsoleResult:
    exit_code: int
    output: str
    verb: str = ""
    activities: list[int] = field(default_factory=list)
    password_required: bool = False
    error_code: str = ""


class Running:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.accounts: set[Any] = set()

    @contextmanager
    def held(self, account: Any) -> Iterator[None]:
        with self.lock:
            if account in self.accounts:
                raise ConsoleBusy()
            self.accounts.add(account)
        try:
            yield
        finally:
            with self.lock:
                self.accounts.discard(account)


RUNNING = Running()


class ConsoleService:
    def __init__(self, user: Any) -> None:
        self.user = user

    @requires(Capability.CONSOLE_RUN)
    def run(self, line: str, password: str = "") -> ConsoleResult:
        words = words_of(line)
        with RUNNING.held(self.user.pk):
            result = self._run(words, password)
        ActivityService(self.user).record(
            RUN,
            target=result.verb,
            detail={
                "verb": result.verb,
                "exit_code": result.exit_code,
                "password_required": result.password_required,
            },
            status=audit.SUCCEEDED if result.exit_code == 0 else audit.FAILED,
            error_code=result.error_code,
        )
        return result

    def _run(self, words: Sequence[str], password: str) -> ConsoleResult:
        stream = CappedText()
        try:
            args = parsed(words, stream)
        except ConsoleStopped as stopped:
            stream.write(stopped.message)
            return ConsoleResult(stopped.status, stream.getvalue())
        verb = " ".join(part for part in (args.command, getattr(args, "verb", "")) if part)
        session = ConsoleSession(args, self.user, password, stream)
        with collecting_jobs() as queued:
            try:
                code = handler_of(args)(session) or 0
            except PasswordNeeded:
                return ConsoleResult(
                    FAILED, stream.getvalue(), verb, list(queued), password_required=True
                )
            except CommandFailed as exc:
                stream.write(f"{PROG}: {exc}\n")
                return ConsoleResult(FAILED, stream.getvalue(), verb, list(queued))
            except APIException as exc:
                stream.write(f"{PROG}: {problem(exc)}\n")
                return ConsoleResult(
                    FAILED,
                    stream.getvalue(),
                    verb,
                    list(queued),
                    error_code=error_code_of(exc),
                )
        return ConsoleResult(code, stream.getvalue(), verb, list(queued))


def words_of(line: str) -> list[str]:
    if len(line) > LINE_MAX:
        raise _invalid(TOO_LONG, "too_long")
    try:
        words = shlex.split(line)
    except ValueError as exc:
        raise _invalid(UNBALANCED, "unbalanced_quotes") from exc
    if words and words[0] in PROGRAM_NAMES:
        words = words[1:]
    if words and words[0] in HELP_WORDS:
        return [*words[1:], "--help"] if words[1:] else []
    return words


def _invalid(message: str, code: str) -> ValidationError:
    return ValidationError({"line": [ErrorDetail(message, code=code)]})
