from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Optional

from .app import Screen
from .kit import layout, text, theme
from .kit.canvas import Area, Canvas
from .kit.dialogs import Confirm
from .kit.keys import Key
from .kit.palette import Style
from .session import Fields, Line, Table, Transcript, plain_lines

SECRET_WARNING = (
    "This prints it in the terminal, where it stays in the scrollback after the "
    "menu closes. Go on?"
)
PAGE = 10
PROBLEM_ROWS = 4


@dataclass
class Outcome:
    code: int
    transcript: Transcript
    problem: str = ""
    stopped: bool = False
    args: Any = None

    @property
    def ok(self) -> bool:
        return self.code == 0 and not self.problem and not self.stopped

    def table(self) -> Optional[Table]:
        tables = self.transcript.tables()
        return tables[-1] if tables else None


def styled(block: Any, columns: int) -> list[tuple[str, Style]]:
    if isinstance(block, Line):
        return [
            (line, theme.BASE) for line in text.wrap(text.safe(block.text), columns)
        ]
    if isinstance(block, Fields):
        return _fields(block, columns)
    lines = plain_lines(block)
    if not block.rows:
        return [(line, theme.MUTED) for line in lines]
    return [(lines[0], theme.COLUMN)] + [(line, theme.BASE) for line in lines[1:]]


def _fields(block: Fields, columns: int) -> list[tuple[str, Style]]:
    pairs = block.pairs()
    width = max((len(name) for name, _ in pairs), default=0)
    lines: list[tuple[str, Style]] = []
    for name, value in pairs:
        wrapped = text.wrap(text.safe(value), max(columns - width - 2, 10)) or [""]
        lines.append((f"{name:<{width}}  {wrapped[0]}", theme.BASE))
        lines += [(" " * (width + 2) + rest, theme.BASE) for rest in wrapped[1:]]
    return lines


class ResultScreen(Screen):
    def __init__(
        self,
        app: Any,
        title: str,
        transcript: Transcript,
        command: str = "",
        secret: bool = False,
    ) -> None:
        super().__init__(app)
        self.title = title
        self.transcript = transcript
        self.command = command
        self.secret = secret
        self.outcome: Optional[Outcome] = None
        self.progress: Sequence[str] = ()
        self.started = time.monotonic()
        self.offset: Optional[int] = None
        self.shape = (80, 10)

    def finish(self, outcome: Outcome) -> None:
        self.outcome = outcome
        self.progress = ()

    def lines(self, columns: int) -> list[tuple[str, Style]]:
        found: list[tuple[str, Style]] = []
        if self.command:
            found += [(line, theme.MUTED) for line in text.wrap(self.command, columns)]
            found.append(("", theme.BASE))
        for block in list(self.transcript.blocks):
            found += styled(block, columns)
        return found

    def said(self, columns: int) -> tuple[str, list[str]]:
        outcome = self.outcome
        if outcome is None:
            return theme.INFO, []
        if outcome.stopped:
            return theme.WARNING, ["Stopped."]
        if outcome.ok:
            return theme.SUCCESS, ["Done."]
        message = outcome.problem or f"It ended with code {outcome.code}."
        return theme.DANGER, text.wrap(
            _sentence(text.safe(message)), max(columns - 4, 10)
        )[:PROBLEM_ROWS]

    def draw(self, canvas: Canvas, area: Area) -> Optional[tuple[int, int]]:
        tone, said = self.said(area.columns)
        status = 1 + max(len(said), 1) + len(self.progress)
        body = area.inset(bottom=status)
        self.shape = (body.columns, body.rows)
        lines = self.lines(body.columns)
        last = max(len(lines) - body.rows, 0)
        start = last if self.offset is None else min(self.offset, last)
        for index, (line, style) in enumerate(lines[start : start + body.rows]):
            canvas.put(body.x, body.y + index, line, style, body.columns)
        if start > 0:
            canvas.put(body.right - 1, body.y, self.app.glyphs.more_up, theme.MUTED)
        if start < last:
            canvas.put(
                body.right - 1, body.bottom - 1, self.app.glyphs.more_down, theme.MUTED
            )
        self._status(
            canvas, Area(area.x, body.bottom + 1, area.columns, status - 1), tone, said
        )
        return None

    def _status(
        self, canvas: Canvas, area: Area, tone: str, said: Sequence[str]
    ) -> None:
        glyphs = self.app.glyphs
        if self.outcome is None:
            elapsed = int(time.monotonic() - self.started)
            layout.tag(
                canvas,
                area.x,
                area.y,
                glyphs,
                theme.INFO,
                f"Running, {elapsed} s. Ctrl+C stops it.",
                limit=area.columns,
            )
            for index, line in enumerate(self.progress):
                canvas.put(
                    area.x + 2, area.y + 1 + index, line, theme.MUTED, area.columns - 2
                )
            return
        style = theme.notice(tone)
        canvas.fill(Area(area.x, area.y, area.columns, len(said)), style)
        canvas.put(area.x + 1, area.y, theme.symbol(glyphs, tone), style)
        for index, line in enumerate(said):
            canvas.put(area.x + 3, area.y + index, line, style, area.columns - 4)

    def key(self, key: Key) -> bool:
        if self.outcome is None:
            return True
        if key.name == "enter":
            self.app.pop()
        elif key.name in ("up", "down", "pageup", "pagedown", "home", "end"):
            self._scroll(key.name)
        elif key.is_text() and key.text == "p":
            self.plainly()
        else:
            return False
        return True

    def _scroll(self, name: str) -> None:
        columns, rows = self.shape
        count = len(self.lines(columns))
        last = max(count - rows, 0)
        current = last if self.offset is None else min(self.offset, last)
        moves = {
            "up": -1,
            "down": 1,
            "pageup": -PAGE,
            "pagedown": PAGE,
            "home": -count,
            "end": count,
        }
        self.offset = min(max(current + moves[name], 0), last)

    def plainly(self) -> None:
        if self.secret and not self.app.modal(
            Confirm("Show it plainly", SECRET_WARNING)
        ):
            return
        with self.app.plain():
            print(self.transcript.plain())
            self.app.pause()

    def hints(self) -> Sequence[tuple[str, str]]:
        if self.outcome is None:
            return (("Ctrl+C", "Stop"),)
        return (("Enter", "Back"), ("↑↓", "Scroll"), ("p", "Show plainly, to copy"))


def _sentence(message: str) -> str:
    message = message.strip()
    return message[:1].upper() + message[1:] if message else message
