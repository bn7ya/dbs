from __future__ import annotations

import getpass
import sys
from collections.abc import Callable
from typing import Any, TypeVar

from django.contrib.auth import get_user_model
from rest_framework.exceptions import ValidationError

from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.terminal import CommandFailed
from dbs.manager.terminal.output import Output

T = TypeVar("T")

ACCOUNT_PASSWORD = "account_password"


class TerminalSession:
    def __init__(self, args: Any) -> None:
        self.args = args
        self.out = Output(as_json=getattr(args, "json", False))
        self.user = self._account(getattr(args, "account", None))
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

    def _account(self, name: str | None) -> Any:
        users = UserRepository()
        if name:
            user = users.find_by_username(name)
            if user is None or not user.is_active:
                raise CommandFailed(f"there is no account named {name!r}.")
            return user
        active = list(
            get_user_model().objects.filter(is_active=True).order_by("username")
        )
        if not active:
            raise CommandFailed(
                "the manager has no account yet. Add one with: django_dbs createuser NAME"
            )
        if len(active) > 1:
            names = ", ".join(user.get_username() for user in active)
            raise CommandFailed(f"pick the account to act as with --as NAME ({names}).")
        return active[0]


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
