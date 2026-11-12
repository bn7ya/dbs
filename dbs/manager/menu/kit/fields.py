from __future__ import annotations

from typing import Optional

from . import text, theme
from .canvas import Canvas
from .keys import Key

MASK = "•"
PLAIN_MASK = "*"


class TextInput:
    def __init__(self, value: str = "", masked: bool = False) -> None:
        self.value = value
        self.masked = masked
        self.caret = len(value)

    def set(self, value: str) -> None:
        self.value = value
        self.caret = len(value)

    def key(self, key: Key) -> bool:
        if key.is_text():
            self._insert(key.text)
        elif key.name == "paste":
            self._insert(" ".join(key.text.splitlines()))
        elif key.name == "backspace":
            if self.caret:
                self.value = self.value[: self.caret - 1] + self.value[self.caret :]
                self.caret -= 1
        elif key.name == "delete":
            self.value = self.value[: self.caret] + self.value[self.caret + 1 :]
        elif key.name == "left":
            self.caret = max(self.caret - 1, 0)
        elif key.name == "right":
            self.caret = min(self.caret + 1, len(self.value))
        elif key.name == "home":
            self.caret = 0
        elif key.name == "end":
            self.caret = len(self.value)
        elif key.ctrl and key.text == "u":
            self.set("")
        else:
            return False
        return True

    def draw(
        self,
        canvas: Canvas,
        x: int,
        y: int,
        columns: int,
        active: bool,
        unicode: bool = True,
    ) -> Optional[tuple[int, int]]:
        style = theme.FIELD_ACTIVE if active else theme.FIELD
        shown = self._shown(unicode)
        room = max(columns - 2, 1)
        before = text.width(shown[: self.caret])
        start = max(before - room + 1, 0)
        window = _window(shown, start, room)
        canvas.put(x, y, " " + text.fit(window, room) + " ", style)
        if not active:
            return None
        caret_x = x + 1 + before - start
        under = _window(shown, before, 1) or " "
        canvas.put(caret_x, y, under, theme.CARET)
        return caret_x, y

    def _shown(self, unicode: bool) -> str:
        if not self.masked:
            return text.safe(self.value)
        return (MASK if unicode else PLAIN_MASK) * len(self.value)

    def _insert(self, typed: str) -> None:
        self.value = self.value[: self.caret] + typed + self.value[self.caret :]
        self.caret += len(typed)


def _window(shown: str, start: int, columns: int) -> str:
    kept = ""
    position = 0
    for cluster, size in text.cells(shown):
        if position >= start and position + size <= start + columns:
            kept += cluster
        position += size
    return kept
