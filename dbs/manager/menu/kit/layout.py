from __future__ import annotations

from collections.abc import Sequence
from typing import Optional

from . import palette, text, theme
from .canvas import Area, Canvas
from .logo import Logo, coverage
from .palette import Style
from .theme import Glyphs

GAP = 3


def box(
    canvas: Canvas,
    area: Area,
    glyphs: Glyphs,
    line: Style = theme.LINE,
    inside: Optional[Style] = theme.BASE,
) -> Area:
    if area.columns < 2 or area.rows < 2:
        return Area(area.x, area.y, 0, 0)
    if inside is not None:
        canvas.fill(area, inside)
    right = area.right - 1
    bottom = area.bottom - 1
    span = glyphs.horizontal * (area.columns - 2)
    canvas.put(area.x, area.y, glyphs.top_left + span + glyphs.top_right, line)
    canvas.put(area.x, bottom, glyphs.bottom_left + span + glyphs.bottom_right, line)
    for y in range(area.y + 1, bottom):
        canvas.put(area.x, y, glyphs.vertical, line)
        canvas.put(right, y, glyphs.vertical, line)
    return area.inset(1, 1, 1, 1)


def divider(
    canvas: Canvas, area: Area, x: int, glyphs: Glyphs, line: Style = theme.LINE
) -> None:
    canvas.put(x, area.y, glyphs.tee_down, line)
    canvas.put(x, area.bottom - 1, glyphs.tee_up, line)
    for y in range(area.y + 1, area.bottom - 1):
        canvas.put(x, y, glyphs.vertical, line)


def rule(
    canvas: Canvas,
    x: int,
    y: int,
    columns: int,
    glyphs: Glyphs,
    line: Style = theme.LINE,
) -> None:
    canvas.put(x, y, glyphs.horizontal * max(columns, 0), line)


def hints(canvas: Canvas, area: Area, pairs: Sequence[tuple[str, str]]) -> None:
    canvas.fill(area, theme.PAGE)
    x = area.x + 1
    for key, label in pairs:
        needed = text.width(key) + 1 + text.width(label)
        if x + needed > area.right:
            break
        x = canvas.put(x, area.y, key, theme.KEY)
        x = canvas.put(x + 1, area.y, label, theme.HINT) + GAP


def tag(
    canvas: Canvas,
    x: int,
    y: int,
    glyphs: Glyphs,
    tone: str,
    word: str,
    under: Optional[Style] = None,
    limit: Optional[int] = None,
) -> int:
    style = theme.tone(tone)
    if under is not None:
        style = under if under.strong else style.over(under.bg)
    return canvas.put(x, y, f"{theme.symbol(glyphs, tone)} {word}", style, limit)


def notice(canvas: Canvas, area: Area, glyphs: Glyphs, tone: str, message: str) -> None:
    style = theme.notice(tone)
    canvas.fill(area, style)
    canvas.put(
        area.x + 1,
        area.y,
        f"{theme.symbol(glyphs, tone)} {message}",
        style,
        area.columns - 2,
    )


def paragraph(
    canvas: Canvas, area: Area, message: str, style: Style = theme.BASE
) -> int:
    lines = text.wrap(message, area.columns)
    for index, line in enumerate(lines[: area.rows]):
        canvas.put(area.x, area.y + index, line, style, area.columns)
    return min(len(lines), area.rows)


def logo(
    canvas: Canvas,
    x: int,
    y: int,
    drawn: Logo,
    columns: int,
    colours: str,
    under: str = theme.SURFACE,
) -> int:
    rows = drawn.rows_for(columns)
    for row_index, row in enumerate(coverage(drawn, columns, rows)):
        for column, (top, bottom) in enumerate(row):
            if top <= 0 and bottom <= 0:
                continue
            canvas.put(
                x + column, y + row_index, *_half_blocks(top, bottom, colours, under)
            )
    return rows


def _half_blocks(
    top: float, bottom: float, colours: str, under: str
) -> tuple[str, Style]:
    if colours in (palette.TRUE, palette.INDEXED):
        return "▀", Style(
            fg=palette.mixed(under, palette.LOGO_BLUE, top),
            bg=palette.mixed(under, palette.LOGO_BLUE, bottom),
        )
    upper, lower = top >= 0.5, bottom >= 0.5
    block = "█" if upper and lower else "▀" if upper else "▄" if lower else " "
    return block, Style(fg=palette.LOGO_BLUE, bg=under)


def centred(area: Area, columns: int, rows: int) -> Area:
    columns = min(columns, area.columns)
    rows = min(rows, area.rows)
    return Area(
        area.x + (area.columns - columns) // 2,
        area.y + (area.rows - rows) // 2,
        columns,
        rows,
    )
