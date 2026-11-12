from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import palette, text
from .palette import Style

CONTINUED = ""
HIDE_CURSOR = "\x1b[?25l"
SHOW_CURSOR = "\x1b[?25h"
CLEAR = "\x1b[2J"


@dataclass(frozen=True)
class Area:
    x: int
    y: int
    columns: int
    rows: int

    def inset(
        self, left: int = 0, top: int = 0, right: int = 0, bottom: int = 0
    ) -> Area:
        return Area(
            self.x + left,
            self.y + top,
            max(self.columns - left - right, 0),
            max(self.rows - top - bottom, 0),
        )

    def row(self, index: int, rows: int = 1) -> Area:
        return Area(
            self.x, self.y + index, self.columns, max(min(rows, self.rows - index), 0)
        )

    @property
    def right(self) -> int:
        return self.x + self.columns

    @property
    def bottom(self) -> int:
        return self.y + self.rows


class Canvas:
    def __init__(
        self,
        columns: int,
        rows: int,
        style: Style = Style(),
        ellipsis: str = text.ELLIPSIS,
    ) -> None:
        self.columns = columns
        self.rows = rows
        self.style = style
        self.ellipsis = ellipsis
        self.cells = [[(" ", style)] * columns for _ in range(rows)]

    @property
    def area(self) -> Area:
        return Area(0, 0, self.columns, self.rows)

    def fill(self, area: Area, style: Style, char: str = " ") -> None:
        for y in range(max(area.y, 0), min(area.bottom, self.rows)):
            for x in range(max(area.x, 0), min(area.right, self.columns)):
                self.cells[y][x] = (char, style)

    def put(
        self,
        x: int,
        y: int,
        value: object,
        style: Optional[Style] = None,
        limit: Optional[int] = None,
    ) -> int:
        if not 0 <= y < self.rows:
            return x
        edge = self.columns if limit is None else min(x + limit, self.columns)
        shown = text.safe(value)
        if limit is not None:
            shown = text.clip(shown, max(edge - x, 0), self.ellipsis)
        row = self.cells[y]
        for cluster, size in text.cells(shown):
            if x + size > edge:
                break
            if x >= 0:
                row[x] = (cluster, style or row[x][1])
                if size == 2:
                    row[x + 1] = (CONTINUED, style or row[x + 1][1])
            x += size
        return x

    def lines(self) -> list[str]:
        return ["".join(char for char, _ in row).rstrip() for row in self.cells]

    def text(self) -> str:
        return "\n".join(self.lines())


class Painter:
    def __init__(self, colours: str) -> None:
        self.colours = colours
        self.shown: Optional[list[list[tuple[str, Style]]]] = None

    def forget(self) -> None:
        self.shown = None

    def paint(self, canvas: Canvas, cursor: Optional[tuple[int, int]] = None) -> str:
        whole = self.shown is None or _size(self.shown) != (canvas.columns, canvas.rows)
        parts = [HIDE_CURSOR]
        if whole:
            parts.append(palette.sequence(canvas.style, self.colours) + CLEAR)
        for y, row in enumerate(canvas.cells):
            before = None if whole else self.shown[y]
            parts.append(self._row(y, row, before))
        self.shown = [list(row) for row in canvas.cells]
        parts.append(palette.RESET)
        if cursor is not None:
            parts.append(f"\x1b[{cursor[1] + 1};{cursor[0] + 1}H{SHOW_CURSOR}")
        return "".join(parts)

    def _row(self, y: int, row: list, before: Optional[list]) -> str:
        first, last = _changed(row, before)
        if first is None:
            return ""
        while first > 0 and row[first][0] == CONTINUED:
            first -= 1
        parts = [f"\x1b[{y + 1};{first + 1}H"]
        style = None
        for char, cell_style in row[first : last + 1]:
            if char == CONTINUED:
                continue
            if cell_style != style:
                parts.append(palette.sequence(cell_style, self.colours))
                style = cell_style
            parts.append(char)
        return "".join(parts)


def _size(cells: list) -> tuple[int, int]:
    return (len(cells[0]) if cells else 0, len(cells))


def _changed(row: list, before: Optional[list]) -> tuple[Optional[int], int]:
    if before is None:
        return 0, len(row) - 1
    differing = [index for index, cell in enumerate(row) if cell != before[index]]
    if not differing:
        return None, 0
    return differing[0], differing[-1]
