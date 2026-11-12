from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Optional

from . import layout, text, theme
from .canvas import Area, Canvas
from .fields import TextInput
from .keys import Key
from .lists import Column, ListView, Row
from .theme import Glyphs

WIDEST = 76
MARGIN = 2
PICK_ROWS = 14

CANCEL = ("Esc", "Cancel")


class Dialog:
    title = ""
    tone = theme.NEUTRAL
    low = False

    def __init__(self) -> None:
        self.done = False
        self.result: Any = None

    def finish(self, result: Any) -> None:
        self.result = result
        self.done = True

    def key(self, key: Key) -> None:
        raise NotImplementedError

    def hints(self) -> Sequence[tuple[str, str]]:
        return (CANCEL,)

    def size(self, columns: int) -> tuple[int, int]:
        raise NotImplementedError

    def body(
        self, canvas: Canvas, area: Area, glyphs: Glyphs, unicode: bool
    ) -> Optional[tuple[int, int]]:
        raise NotImplementedError

    def draw(
        self, canvas: Canvas, glyphs: Glyphs, unicode: bool = True
    ) -> Optional[tuple[int, int]]:
        room = canvas.area.inset(MARGIN, 1, MARGIN, 1)
        columns, rows = self.size(min(room.columns - 4, WIDEST))
        frame = layout.centred(room, columns + 4, rows + 4)
        if self.low:
            frame = Area(frame.x, room.bottom - frame.rows, frame.columns, frame.rows)
        line = theme.tone(self.tone) if self.tone != theme.NEUTRAL else theme.ACCENT
        inside = layout.box(canvas, frame, glyphs, line)
        canvas.put(
            inside.x + 1, inside.y, self.title, theme.HEADING, inside.columns - 2
        )
        return self.body(canvas, inside.inset(1, 2, 1, 0), glyphs, unicode)


def _buttons(
    canvas: Canvas, area: Area, labels: Sequence[str], chosen: int, danger: int = -1
) -> None:
    x = area.x
    for index, label in enumerate(labels):
        if index == chosen:
            style = theme.DANGER_BUTTON if index == danger else theme.BUTTON
        else:
            style = theme.DANGER_IDLE if index == danger else theme.BUTTON_IDLE
        x = canvas.put(x, area.y, f"  {label}  ", style) + 2


class Message(Dialog):
    def __init__(self, title: str, message: str, tone: str = theme.NEUTRAL) -> None:
        super().__init__()
        self.title = title
        self.message = message
        self.tone = tone

    def size(self, columns: int) -> tuple[int, int]:
        lines = text.wrap(self.message, columns)
        return min(
            max((text.width(line) for line in lines), default=0) + 2, columns
        ), len(lines) + 2

    def body(self, canvas, area, glyphs, unicode):
        used = layout.paragraph(canvas, area, self.message)
        _buttons(canvas, area.row(used + 1), ("OK",), 0)
        return None

    def key(self, key: Key) -> None:
        if key.name in ("enter", "escape") or key.is_text():
            self.finish(None)

    def hints(self):
        return (("Enter", "Close"),)


class Confirm(Dialog):
    def __init__(
        self,
        title: str,
        message: str,
        yes: str = "Yes",
        no: str = "No",
        danger: bool = False,
    ) -> None:
        super().__init__()
        self.title = title
        self.message = message
        self.labels = (yes, no)
        self.danger = danger
        self.chosen = 1
        if danger:
            self.tone = theme.DANGER

    def size(self, columns: int) -> tuple[int, int]:
        lines = text.wrap(self.message, columns)
        widest = max(
            [text.width(line) for line in lines]
            + [sum(len(label) + 6 for label in self.labels)]
        )
        return min(widest + 2, columns), len(lines) + 2

    def body(self, canvas, area, glyphs, unicode):
        used = layout.paragraph(canvas, area, self.message)
        _buttons(
            canvas,
            area.row(used + 1),
            self.labels,
            self.chosen,
            0 if self.danger else -1,
        )
        return None

    def key(self, key: Key) -> None:
        if key.name in ("left", "right", "tab", "backtab", "up", "down"):
            self.chosen = 1 - self.chosen
        elif key.name == "enter":
            self.finish(self.chosen == 0)
        elif key.name == "escape" or (key.is_text() and key.text.lower() == "n"):
            self.finish(False)
        elif key.is_text() and key.text.lower() == "y":
            self.finish(True)

    def hints(self):
        return (("←→", "Choose"), ("Enter", "Confirm"), ("y/n", "Answer"), CANCEL)


class Ask(Dialog):
    def __init__(
        self,
        title: str,
        message: str = "",
        masked: bool = False,
        twice: bool = False,
        value: str = "",
        danger: bool = False,
    ) -> None:
        super().__init__()
        self.title = title
        self.message = message
        self.inputs = [TextInput(value, masked)]
        if twice:
            self.inputs.append(TextInput("", masked))
        self.current = 0
        self.problem = ""
        if danger:
            self.tone = theme.DANGER

    def size(self, columns: int) -> tuple[int, int]:
        lines = text.wrap(self.message, columns) if self.message else []
        return columns, len(lines) + (1 if lines else 0) + 2 * len(self.inputs) + (
            1 if self.problem else 0
        )

    def body(self, canvas, area, glyphs, unicode):
        used = layout.paragraph(canvas, area, self.message) if self.message else 0
        y = area.y + used + (1 if used else 0)
        cursor = None
        for index, field in enumerate(self.inputs):
            if len(self.inputs) > 1:
                canvas.put(area.x, y, "Again" if index else "Type it", theme.MUTED)
                y += 1
            found = field.draw(
                canvas, area.x, y, area.columns, index == self.current, unicode
            )
            cursor = found or cursor
            y += 1 if len(self.inputs) > 1 else 2
        if self.problem:
            layout.tag(
                canvas,
                area.x,
                area.bottom - 1,
                glyphs,
                theme.DANGER,
                self.problem,
                limit=area.columns,
            )
        return cursor

    def key(self, key: Key) -> None:
        if key.name == "escape" or (key.ctrl and key.text == "c"):
            self.finish(None)
        elif key.name in ("tab", "down", "up", "backtab") and len(self.inputs) > 1:
            self.current = 1 - self.current
        elif key.name == "enter":
            self._entered()
        else:
            self.inputs[self.current].key(key)
            self.problem = ""

    def _entered(self) -> None:
        if self.current < len(self.inputs) - 1:
            self.current += 1
            return
        if len(self.inputs) > 1 and self.inputs[0].value != self.inputs[1].value:
            self.problem = "The two differ. Type them again."
            self.inputs[1].set("")
            return
        self.finish(self.inputs[0].value)

    def hints(self):
        return (("Enter", "Continue"), CANCEL)


@dataclass(frozen=True)
class Choice:
    label: str
    value: Any
    detail: str = ""
    tone: str = ""
    danger: bool = False


class Pick(Dialog):
    def __init__(
        self,
        title: str,
        choices: Sequence[Choice],
        many: bool = False,
        chosen: Sequence[Any] = (),
        empty: str = "Nothing to choose from.",
        message: str = "",
    ) -> None:
        super().__init__()
        self.title = title
        self.choices = list(choices)
        self.many = many
        self.message = message
        self.marked = [
            choice.value for choice in self.choices if choice.value in chosen
        ]
        self.view = ListView(columns=(Column(""), Column("")), empty=empty)
        self._show()
        if chosen and not many:
            values = [choice.value for choice in self.choices]
            if chosen[0] in values:
                self.view.cursor = values.index(chosen[0])

    def _show(self) -> None:
        rows = []
        for choice in self.choices:
            label = choice.label
            if self.many:
                label = f"{'[x]' if choice.value in self.marked else '[ ]'} {label}"
            tones = ("", choice.tone) if choice.tone else ()
            rows.append(
                Row((label, choice.detail), choice, tones, danger=choice.danger)
            )
        self.view.show(rows)

    def size(self, columns: int) -> tuple[int, int]:
        widest = max(
            [
                text.width(choice.label) + text.width(choice.detail) + 10
                for choice in self.choices
            ]
            + [text.width(self.title) + 4, 30]
        )
        extra = len(text.wrap(self.message, columns)) + 1 if self.message else 0
        return min(widest, columns), min(len(self.choices), PICK_ROWS) + 1 + extra

    def body(self, canvas, area, glyphs, unicode):
        if self.message:
            used = layout.paragraph(canvas, area, self.message, theme.MUTED)
            area = area.inset(top=used + 1)
        self.view.draw(canvas, area, glyphs)
        return None

    def key(self, key: Key) -> None:
        if self.view.filtering:
            self.view.key(key)
            return
        if key.name == "escape" or (key.ctrl and key.text == "c"):
            self.finish(None)
        elif self.many and key.is_text() and key.text == " ":
            self._toggle()
        elif key.name == "enter":
            self._entered()
        else:
            self.view.key(key)

    def _toggle(self) -> None:
        row = self.view.selected
        if row is None:
            return
        value = row.data.value
        if value in self.marked:
            self.marked.remove(value)
        else:
            self.marked.append(value)
        self._show()

    def _entered(self) -> None:
        if self.many:
            self.finish(list(self.marked))
            return
        row = self.view.selected
        self.finish(row.data.value if row is not None else None)

    def hints(self):
        if self.many:
            return (
                ("↑↓", "Move"),
                ("Space", "Mark"),
                ("Enter", "Done"),
                ("/", "Filter"),
                CANCEL,
            )
        return (("↑↓", "Move"), ("Enter", "Choose"), ("/", "Filter"), CANCEL)
