from __future__ import annotations

import io
from typing import Any

from dbs import audit
from dbs.manager.adapters import jobs
from dbs.manager.console.exceptions import PasswordNeeded
from dbs.manager.terminal import CommandFailed
from dbs.manager.terminal.output import Output
from dbs.manager.terminal.session import TerminalSession

OUTPUT_MAX = 256 * 1024
CUT = "\n[the rest of the output was cut at 256 KiB]\n"
UNFINISHED = (audit.QUEUED, audit.RUNNING)


class CappedText(io.StringIO):
    def __init__(self, limit: int = OUTPUT_MAX) -> None:
        super().__init__()
        self.limit = limit
        self.cut = False

    def write(self, text: str) -> int:
        if self.cut:
            return len(text)
        room = self.limit - self.tell()
        if len(text) > room:
            super().write(text[: max(room, 0)])
            super().write(CUT)
            self.cut = True
            return len(text)
        return super().write(text)


class ConsoleSession(TerminalSession):
    waits = False

    def __init__(self, args: Any, user: Any, password: str, stream: CappedText) -> None:
        self.args = args
        self.user = user
        self.out = Output(as_json=getattr(args, "json", False), stream=stream)
        self._password = password or None

    def password(self) -> str:
        if not self._password:
            raise PasswordNeeded()
        return self._password

    def secret(
        self, prompt: str, from_stdin: bool = False, stdin_option: str = ""
    ) -> str:
        raise CommandFailed(
            f"the console cannot ask for the {prompt.lower()}; use the interface or a "
            "terminal for this."
        )

    def outcome(self, entry: Any, done: str) -> int:
        if entry.status in UNFINISHED:
            self.out.say(
                f"Started; follow it as activity {entry.pk}.",
                jobs.described(self.user, entry),
            )
            return 0
        return super().outcome(entry, done)

    def agrees(self, question: str) -> bool:
        raise CommandFailed(
            "this needs a person to answer; use the interface or a terminal for this."
        )

    def confirm(self, question: str, *, expected: str | None = None) -> None:
        if getattr(self.args, "yes", False):
            return
        if expected is not None and getattr(self.args, "confirm_name", None) == expected:
            return
        if expected is None or not hasattr(self.args, "confirm_name"):
            raise CommandFailed("this needs a confirmation; add --yes.")
        raise CommandFailed(f"this needs a confirmation; add --confirm-name {expected}.")
