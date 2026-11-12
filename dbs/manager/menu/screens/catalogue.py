from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .. import commands, forms, meanings
from ..app import Screen
from ..commands import Verb
from ..kit import layout, theme
from ..kit.canvas import Area, Canvas
from ..kit.keys import Key
from ..kit.lists import Column, ListView, Row

LEFT_OUT = frozenset({("menu",)})
NOTE = (
    "Every command the manager has. Each opens as a form and shows what it would run."
)


def offered() -> list[Verb]:
    return [verb for verb in commands.catalogue() if verb.path not in LEFT_OUT]


class CatalogueScreen(Screen):
    title = "All commands"

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self.view = ListView(
            columns=(Column("Command"), Column("What it does")), yields=1
        )
        self.view.show([Row((verb.name, verb.help), verb) for verb in offered()])

    def draw(self, canvas: Canvas, area: Area) -> None:
        used = layout.paragraph(
            canvas, Area(area.x, area.y, area.columns, 2), NOTE, theme.MUTED
        )
        self.view.draw(
            canvas, area.inset(top=used + 1), self.app.glyphs, not self.app.in_sidebar
        )
        return None

    def key(self, key: Key) -> bool:
        if self.view.filtering:
            return self.view.key(key)
        row = self.view.selected
        if key.name == "enter" and row is not None:
            self.open(row.data)
            return True
        return self.view.key(key)

    def open(self, verb: Verb) -> None:
        if verb.path in meanings.NAMED_ONLY or not meanings.offered(verb):
            forms.launch(self.app, verb, {})
        else:
            self.app.push(forms.FormScreen(self.app, verb))

    def hints(self) -> Sequence[tuple[str, str]]:
        return (("↑↓", "Move"), ("Enter", "Open"), ("/", "Filter"))
