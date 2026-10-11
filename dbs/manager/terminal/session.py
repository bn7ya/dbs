from __future__ import annotations

import getpass
import sys
from collections.abc import Callable
from typing import Any, TypeVar

from rest_framework.exceptions import ValidationError

from dbs.manager.adapters import accounts, jobs
from dbs.manager.terminal import CommandFailed
from dbs.manager.terminal.output import Output

T = TypeVar("T")

ACCOUNT_PASSWORD = "account_password"


class TerminalSession:
    def __init__(self, args: Any) -> None:
        self.args = args
        self.out = Output(as_json=getattr(args, "json", False))
        self.user = accounts.acting(getattr(args, "account", None))
        self._password: str | None = None

    def password(self) -> str:
        if self._password is None:
            if getattr(self.args, "password_stdin", False):
                given = sys.stdin.readline().rstrip("\n")
            else:
                given = _ask(
                    f"Password for {self.user.get_username()}: ", "--password-stdin"
                )
            if not given:
                raise CommandFailed("the password is empty.")
            self._password = given
        return self._password

    def guarded(self, call: Callable[[str], T]) -> T:
        try:
            return call("")
        except ValidationError as exc:
            if not isinstance(exc.detail, dict) or ACCOUNT_PASSWORD not in exc.detail:
                raise
        return call(self.password())

    def secret(
        self, prompt: str, from_stdin: bool = False, stdin_option: str = ""
    ) -> str:
        if from_stdin:
            given = sys.stdin.readline().rstrip("\n")
        else:
            given = _ask(f"{prompt}: ", stdin_option)
        if not given:
            raise CommandFailed(f"the {prompt.lower()} is empty.")
        return given

    def outcome(self, entry: Any, done: str) -> int:
        if jobs.succeeded(entry):
            self.out.say(done, jobs.described(self.user, entry))
            return 0
        if self.out.as_json:
            self.out.json(jobs.described(self.user, entry))
            return 1
        raise CommandFailed(f"failed: {jobs.failure(entry)}")

    def confirm(self, question: str, *, expected: str | None = None) -> None:
        if getattr(self.args, "yes", False):
            return
        if not interactive():
            raise CommandFailed("this needs a confirmation; pass --yes from a script.")
        try:
            answer = input(f"{question} ").strip()
        except EOFError:
            answer = ""
        if expected is None and answer.lower() in ("y", "yes"):
            return
        if expected is not None and answer == expected:
            return
        raise CommandFailed("stopped; nothing was changed.")


def interactive() -> bool:
    return sys.stdin.isatty()


def _ask(prompt: str, stdin_option: str) -> str:
    if not interactive():
        hint = (
            f"pass {stdin_option} from a script"
            if stdin_option
            else "run it in a terminal"
        )
        raise CommandFailed(f"this asks for a secret to be typed; {hint}.")
    try:
        return getpass.getpass(prompt)
    except EOFError:
        return ""
