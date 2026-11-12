from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Optional

from dbs.manager.terminal import CommandFailed
from dbs.manager.terminal.output import Column, Output, label, text, value_of
from dbs.manager.terminal.session import TerminalSession

from .kit.dialogs import Ask, Confirm

OUTPUT_MAX = 256 * 1024
CUT = "[the rest of the output was cut at 256 KiB]"
STOPPED = "stopped; nothing was changed."
YES_NO = "[y/N]"


@dataclass
class Line:
    text: str


@dataclass
class Table:
    rows: Sequence[Mapping[str, Any]]
    columns: Sequence[Column]
    empty: str
    data: Any = None

    def cells(self) -> list[list[str]]:
        return [
            [text(value_of(row, key)) for _, key in self.columns] for row in self.rows
        ]

    def headers(self) -> list[str]:
        return [header for header, _ in self.columns]


@dataclass
class Fields:
    data: Mapping[str, Any]
    names: Sequence[str]

    def pairs(self) -> list[tuple[str, str]]:
        return [
            (label(name), text(self.data[name]))
            for name in self.names
            if name in self.data
        ]


@dataclass
class Transcript:
    blocks: list = field(default_factory=list)
    size: int = 0
    cut: bool = False
    open_line: bool = False

    def add(self, block: Any, size: int) -> None:
        if self.cut:
            return
        if self.size + size > OUTPUT_MAX:
            self.blocks.append(Line(CUT))
            self.cut = True
            return
        self.size += size
        self.blocks.append(block)
        self.open_line = False

    def write(self, message: str, end: str = "\n") -> None:
        pieces = (message + end).split("\n")
        for index, piece in enumerate(pieces):
            last = index == len(pieces) - 1
            if last and not piece:
                break
            if self.open_line and self.blocks and isinstance(self.blocks[-1], Line):
                self.blocks[-1].text += piece
                self.size += len(piece)
            else:
                self.add(Line(piece), len(piece) + 1)
            self.open_line = last

    def tables(self) -> list[Table]:
        return [block for block in self.blocks if isinstance(block, Table)]

    def plain(self) -> str:
        lines: list[str] = []
        for block in self.blocks:
            lines += plain_lines(block)
        return "\n".join(lines)


def plain_lines(block: Any) -> list[str]:
    if isinstance(block, Line):
        return [block.text]
    if isinstance(block, Fields):
        pairs = block.pairs()
        width = max((len(name) for name, _ in pairs), default=0)
        return [f"{name:<{width}}  {value}" for name, value in pairs]
    if not block.rows:
        return [block.empty] if block.empty else []
    cells = [block.headers(), *block.cells()]
    widths = [max(len(line[index]) for line in cells) for index in range(len(cells[0]))]
    return [
        "  ".join(cell.ljust(width) for cell, width in zip(line, widths)).rstrip()
        for line in cells
    ]


class MenuOutput(Output):
    def __init__(self, transcript: Transcript) -> None:
        super().__init__(as_json=False)
        self.transcript = transcript

    def line(self, message: str = "", *, end: str = "\n") -> None:
        self.transcript.write(str(message), end)

    def json(self, data: Any) -> None:
        self.line(json.dumps(data, indent=2, default=str, ensure_ascii=False))

    def table(
        self,
        rows: Sequence[Mapping[str, Any]],
        columns: Sequence[Column],
        *,
        empty: str,
        data: Any = None,
    ) -> None:
        kept = [dict(row) for row in rows]
        self.transcript.add(
            Table(kept, tuple(columns), empty, data), sum(len(str(row)) for row in kept)
        )

    def fields(self, data: Mapping[str, Any], names: Iterable[str]) -> None:
        self.transcript.add(Fields(dict(data), tuple(names)), len(str(data)))

    def say(self, message: str, data: Any = None) -> None:
        self.line(message)


class MenuSession(TerminalSession):
    waits = False

    def __init__(
        self,
        args: Any,
        user: Any,
        app: Any,
        transcript: Transcript,
        answers: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.args = args
        self.user = user
        self.app = app
        self.out = MenuOutput(transcript)
        self.answers = dict(answers or {})
        self._password = None

    def password(self) -> str:
        if self._password is None:
            given = self.app.modal(
                Ask(
                    f"Password for {self.user.get_username()}",
                    "This asks for your account password.",
                    masked=True,
                )
            )
            if given is None:
                raise CommandFailed(STOPPED)
            if not given:
                raise CommandFailed("the password is empty.")
            self._password = given
        return self._password

    def secret(
        self, prompt: str, from_stdin: bool = False, stdin_option: str = ""
    ) -> str:
        if prompt in self.answers:
            return self.answers.pop(prompt)
        given = self.app.modal(Ask(prompt, masked=True))
        if given is None:
            raise CommandFailed(STOPPED)
        if not given:
            raise CommandFailed(f"the {prompt.lower()} is empty.")
        return given

    def agrees(self, question: str) -> bool:
        return bool(self.app.modal(Confirm("Answer", _asked(question))))

    def confirm(self, question: str, *, expected: Any = None) -> None:
        if getattr(self.args, "yes", False):
            return
        if expected is None:
            agreed = self.app.modal(Confirm("Confirm", _asked(question), danger=True))
        else:
            agreed = (
                self.app.modal(Ask("Confirm by name", question, danger=True))
                == expected
            )
        if not agreed:
            raise CommandFailed(STOPPED)


def _asked(question: str) -> str:
    return question.replace(YES_NO, "").strip()
