from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Optional

from . import text, theme
from .canvas import Area, Canvas
from .keys import Key
from .theme import Glyphs

GAP = 2
MARK = 2
NARROWEST = 4


@dataclass(frozen=True)
class Column:
    title: str
    align: str = "left"


@dataclass
class Row:
    cells: Sequence[Any]
    data: Any = None
    tones: Sequence[str] = ()
    danger: bool = False
    muted: bool = False

    def cell(self, index: int) -> str:
        return text.safe(self.cells[index]) if index < len(self.cells) else ""

    def tone(self, index: int) -> str:
        return self.tones[index] if index < len(self.tones) else ""

    def matches(self, wanted: str) -> bool:
        return any(
            wanted in self.cell(index).lower() for index in range(len(self.cells))
        )


@dataclass
class ListView:
    columns: Sequence[Column] = ()
    empty: str = ""
    rows: list[Row] = field(default_factory=list)
    cursor: int = 0
    offset: int = 0
    filtering: bool = False
    wanted: str = ""
    yields: Optional[int] = None

    def show(self, rows: Sequence[Row], keep: bool = True) -> None:
        self.rows = list(rows)
        if not keep:
            self.cursor = 0
            self.offset = 0
        self._settle()

    def visible(self) -> list[Row]:
        if not self.wanted:
            return self.rows
        wanted = self.wanted.lower()
        return [row for row in self.rows if row.matches(wanted)]

    @property
    def selected(self) -> Optional[Row]:
        rows = self.visible()
        return rows[self.cursor] if rows else None

    def key(self, key: Key) -> bool:
        if self.filtering:
            return self._filter_key(key)
        if key.is_text() and key.text == "/":
            self.filtering = True
            return True
        return self._move(key)

    def draw(
        self, canvas: Canvas, area: Area, glyphs: Glyphs, focused: bool = True
    ) -> None:
        rows = self.visible()
        body = area
        if self.filtering or self.wanted:
            self._draw_filter(canvas, area.row(0), glyphs)
            body = area.inset(top=1)
        if not rows:
            message = "Nothing matches." if self.wanted else self.empty
            canvas.put(body.x + MARK, body.y, message, theme.MUTED, body.columns - MARK)
            return
        widths = self._widths(rows, body.columns - MARK)
        if any(column.title for column in self.columns):
            self._draw_cells(
                canvas,
                body.x + MARK,
                body.y,
                [column.title for column in self.columns],
                widths,
                [theme.COLUMN] * len(widths),
            )
            body = body.inset(top=1)
        self._scroll(body.rows)
        for line, row in enumerate(rows[self.offset : self.offset + body.rows]):
            index = self.offset + line
            self._draw_row(
                canvas,
                body,
                body.y + line,
                row,
                widths,
                glyphs,
                index == self.cursor,
                focused,
            )
        self._draw_more(canvas, body, len(rows), glyphs)

    def _draw_row(self, canvas, body, y, row, widths, glyphs, current, focused) -> None:
        base = (
            theme.DANGER_IDLE.over(theme.SURFACE)
            if row.danger
            else theme.MUTED
            if row.muted
            else theme.BASE
        )
        if current:
            base = theme.CURSOR if focused else theme.CHOSEN
            canvas.fill(Area(body.x, y, body.columns, 1), base)
            canvas.put(body.x, y, glyphs.pointer, base)
        styles = []
        for index in range(len(widths)):
            tone = row.tone(index)
            if tone and not (current and focused):
                styles.append(theme.tone(tone).over(base.bg))
            else:
                styles.append(base)
        self._draw_cells(
            canvas,
            body.x + MARK,
            y,
            [row.cell(index) for index in range(len(widths))],
            widths,
            styles,
        )

    def _draw_cells(self, canvas, x, y, cells, widths, styles) -> None:
        for index, width in enumerate(widths):
            align = self.columns[index].align if index < len(self.columns) else "left"
            canvas.put(
                x,
                y,
                text.fit(cells[index], width, align, canvas.ellipsis),
                styles[index],
            )
            x += width + GAP

    def _draw_filter(self, canvas: Canvas, area: Area, glyphs: Glyphs) -> None:
        style = theme.FIELD_ACTIVE if self.filtering else theme.FIELD
        canvas.fill(area, style)
        canvas.put(
            area.x + 1, area.y, f"Filter: {self.wanted}", style, area.columns - 2
        )

    def _draw_more(
        self, canvas: Canvas, body: Area, count: int, glyphs: Glyphs
    ) -> None:
        if self.offset > 0:
            canvas.put(body.right - 1, body.y, glyphs.more_up, theme.MUTED)
        if self.offset + body.rows < count:
            canvas.put(body.right - 1, body.bottom - 1, glyphs.more_down, theme.MUTED)

    def _widths(self, rows: Sequence[Row], room: int) -> list[int]:
        count = max(len(self.columns), max((len(row.cells) for row in rows), default=0))
        widths = []
        for index in range(count):
            title = self.columns[index].title if index < len(self.columns) else ""
            widths.append(
                max(text.width(title), *(text.width(row.cell(index)) for row in rows))
            )
        while widths and sum(widths) + GAP * (len(widths) - 1) > room:
            narrowed = self._narrowed(widths)
            if widths[narrowed] <= NARROWEST:
                break
            widths[narrowed] -= 1
        return widths

    def _narrowed(self, widths: Sequence[int]) -> int:
        if (
            self.yields is not None
            and self.yields < len(widths)
            and widths[self.yields] > NARROWEST
        ):
            return self.yields
        return max(range(len(widths)), key=lambda index: widths[index])

    def _scroll(self, height: int) -> None:
        if height <= 0:
            return
        if self.cursor < self.offset:
            self.offset = self.cursor
        if self.cursor >= self.offset + height:
            self.offset = self.cursor - height + 1

    def _settle(self) -> None:
        count = len(self.visible())
        self.cursor = min(max(self.cursor, 0), max(count - 1, 0))
        self.offset = min(self.offset, self.cursor)

    def _move(self, key: Key) -> bool:
        count = len(self.visible())
        steps = {"up": -1, "down": 1, "pageup": -10, "pagedown": 10}
        if key.name in steps:
            self.cursor = min(max(self.cursor + steps[key.name], 0), max(count - 1, 0))
            return True
        if key.name == "home":
            self.cursor = 0
            return True
        if key.name == "end":
            self.cursor = max(count - 1, 0)
            return True
        return False

    def _filter_key(self, key: Key) -> bool:
        if key.name == "escape":
            self.filtering = False
            self.wanted = ""
        elif key.name == "enter":
            self.filtering = False
        elif key.name == "backspace":
            self.wanted = self.wanted[:-1]
        elif key.is_text():
            self.wanted += key.text
        elif key.name == "paste":
            self.wanted += key.text.replace("\n", " ")
        else:
            return self._move(key)
        self._settle()
        return True
