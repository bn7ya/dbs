from __future__ import annotations

import posixpath
from collections.abc import Sequence
from typing import Any, Optional

from .kit import layout, text, theme
from .kit.canvas import Area, Canvas
from .kit.dialogs import Ask, Choice, Dialog, Pick
from .kit.keys import Key
from .kit.lists import Column, ListView, Row
from .sources import FILE, FOLDER, LINK, Entry, Folder, LocalDisk, Unreadable

UNITS = ("B", "KB", "MB", "GB", "TB")
PICK_FILE = "file"
PICK_FOLDER = "folder"
PICK_ANY = "any"
PICK_TARGET = "target"
DIALOG_ROWS = 18
DIALOG_COLUMNS = 72


def size(count: Optional[int]) -> str:
    if count is None:
        return ""
    value = float(count)
    for unit in UNITS[:-1]:
        if value < 1024:
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} {UNITS[-1]}"


class Explorer:
    def __init__(self, app: Any, source: Any, start: Optional[str] = None) -> None:
        self.app = app
        self.source = source
        self.folder: Optional[Folder] = None
        self.problem = ""
        self.view = ListView(
            columns=(Column("Name"), Column("Size", "right"), Column("Modified")),
            empty="This folder is empty.",
        )
        self.open(start)

    def open(self, path: Optional[str], select: str = "") -> bool:
        self.app.busy("Reading the folder")
        try:
            folder = self.source.list(path)
        except Unreadable as exc:
            self.problem = str(exc)
            return False
        self.problem = ""
        self.folder = folder
        self.view.wanted = ""
        self.view.show([_row(entry) for entry in folder.entries], keep=False)
        if select:
            names = [entry.name for entry in folder.entries]
            if select in names:
                self.view.cursor = names.index(select)
        return True

    def refresh(self) -> None:
        if self.folder is not None:
            chosen = self.selected
            self.open(self.folder.path, chosen.name if chosen else "")

    def up(self) -> bool:
        if self.folder is None or not self.folder.parent:
            return False
        came_from = posixpath.basename(
            self.folder.path.rstrip("/\\").replace("\\", "/")
        )
        return self.open(self.folder.parent, came_from)

    def go(self) -> None:
        if self.folder is None or not self.folder.roots:
            return
        chosen = self.app.modal(
            Pick("Go to", [Choice(root, root) for root in self.folder.roots])
        )
        if chosen:
            self.open(chosen)

    @property
    def selected(self) -> Optional[Entry]:
        row = self.view.selected
        return row.data if row is not None else None

    @property
    def path(self) -> str:
        return self.folder.path if self.folder is not None else ""

    def key(self, key: Key) -> bool:
        if self.view.filtering:
            return self.view.key(key)
        chosen = self.selected
        if key.name == "enter" and chosen is not None and chosen.opens:
            self.open(chosen.path)
        elif key.name in ("backspace", "left"):
            return self.up()
        elif key.is_text() and key.text == "g":
            self.go()
        elif key.is_text() and key.text == "r":
            self.refresh()
        else:
            return self.view.key(key)
        return True

    def draw(self, canvas: Canvas, area: Area, focused: bool = True) -> None:
        glyphs = self.app.glyphs
        shown = text.tail(
            text.safe(f"{self.source.title}: {self.path}"),
            area.columns,
            canvas.ellipsis,
        )
        canvas.put(area.x, area.y, shown, theme.ACCENT)
        top = 1
        if self.problem:
            layout.notice(canvas, area.row(1), glyphs, theme.DANGER, self.problem)
            top = 3
        elif self.folder is not None and self.folder.note:
            canvas.put(area.x, area.y + 1, self.folder.note, theme.MUTED, area.columns)
            top = 2
        self.view.draw(canvas, area.inset(top=top), glyphs, focused)


def _row(entry: Entry) -> Row:
    name = entry.name + (
        "/" if entry.kind == FOLDER else " (link)" if entry.kind == LINK else ""
    )
    return Row(
        (name, size(entry.size), entry.modified),
        entry,
        muted=entry.kind not in (FOLDER, FILE),
    )


class PathDialog(Dialog):
    def __init__(
        self, app: Any, source: Any, mode: str, title: str, start: Optional[str] = None
    ) -> None:
        super().__init__()
        self.app = app
        self.mode = mode
        self.title = title
        self.explorer = Explorer(app, source, start)

    def size(self, columns: int) -> tuple[int, int]:
        return min(columns, DIALOG_COLUMNS), DIALOG_ROWS

    def body(self, canvas, area, glyphs, unicode):
        self.explorer.draw(canvas, area)
        return None

    def key(self, key: Key) -> None:
        explorer = self.explorer
        if explorer.view.filtering:
            explorer.key(key)
            return
        chosen = explorer.selected
        if key.name == "escape" or (key.ctrl and key.text == "c"):
            self.finish(None)
        elif key.name == "enter" and chosen is not None and not chosen.opens:
            if self.mode in (PICK_FILE, PICK_ANY) and chosen.kind == FILE:
                self.finish(chosen.path)
        elif key.is_text() and key.text == "s":
            self._use()
        elif key.is_text() and key.text == "n" and self.mode == PICK_TARGET:
            self._named()
        elif key.is_text() and key.text == "t":
            typed = self.app.modal(Ask("Type the path", value=explorer.path))
            if typed:
                self.finish(typed)
        else:
            explorer.key(key)

    def _use(self) -> None:
        chosen = self.explorer.selected
        if self.mode == PICK_ANY and chosen is not None:
            self.finish(chosen.path)
        elif self.mode in (PICK_FOLDER, PICK_TARGET) and self.explorer.path:
            self.finish(self.explorer.path)

    def _named(self) -> None:
        name = self.app.modal(Ask("File name", "It is written in the folder shown."))
        if name:
            self.finish(_joined(self.explorer.source, self.explorer.path, name))

    def hints(self) -> Sequence[tuple[str, str]]:
        pairs = [("Enter", "Open"), ("Backspace", "Up")]
        if self.mode in (PICK_FILE, PICK_ANY):
            pairs[0] = ("Enter", "Open or choose")
        if self.mode == PICK_ANY:
            pairs.append(("s", "Choose the selected"))
        if self.mode in (PICK_FOLDER, PICK_TARGET):
            pairs.append(("s", "Use this folder"))
        if self.mode == PICK_TARGET:
            pairs.append(("n", "Name a file"))
        return (*pairs, ("t", "Type a path"), ("g", "Go to"), ("Esc", "Cancel"))


def _joined(source: Any, folder: str, name: str) -> str:
    if isinstance(source, LocalDisk):
        import os

        return os.path.join(folder, name)
    return posixpath.join(folder, name)
