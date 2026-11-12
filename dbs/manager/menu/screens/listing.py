from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Optional

from dbs.manager import permissions
from dbs.manager.permissions import Capability

from .. import commands, forms, pickers, running
from ..app import Screen
from ..explorer import PICK_FILE, PICK_TARGET, Explorer, PathDialog
from ..kit import layout, text, theme
from ..kit.canvas import Area, Canvas
from ..kit.dialogs import Ask, Choice, Pick
from ..kit.keys import Key
from ..kit.lists import Column, ListView, Row
from ..session import Table
from ..sources import FILE, ApplicationFiles, LocalDisk, ServerFolders
from . import sections
from .sections import Action, Listing

HIDDEN_COLUMNS = ("ID",)
STATE_COLUMNS = ("STATUS", "VALIDATION", "LAST", "RESULT")
STATES = {
    "ok": (theme.SUCCESS, "Ready"),
    "problem": (theme.WARNING, "Needs attention"),
    "unknown": (theme.NEUTRAL, "Not checked"),
    "failed": (theme.DANGER, "Failed"),
    "succeeded": (theme.SUCCESS, "Succeeded"),
    "running": (theme.INFO, "Running"),
    "queued": (theme.NEUTRAL, "Queued"),
    "verified": (theme.SUCCESS, "Verified"),
    "structure_ok": (theme.NEUTRAL, "Structure checked"),
}
MOMENT = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})")


def moment(value: str) -> str:
    return MOMENT.sub(r"\1 \2", value)[:16] if MOMENT.match(value) else value


def state(glyphs: Any, value: str) -> tuple[str, str]:
    tone, word = STATES[value]
    return f"{theme.symbol(glyphs, tone)} {word}", tone


def allowed(app: Any, action: Action) -> bool:
    return not action.needs or permissions.can(app.user, action.needs)


class ListingScreen(Screen):
    def __init__(
        self, app: Any, listing: Listing, parent: str = "", parent_title: str = ""
    ) -> None:
        super().__init__(app)
        self.listing = listing
        self.parent = parent
        self.title = listing.title
        self.view = ListView(empty=listing.empty)
        self.rows: list[dict] = []
        self.problem = ""
        self.load()

    def values(self) -> dict[str, Any]:
        return {key: self.parent for key in self.listing.fill}

    def load(self) -> None:
        outcome = running.run(
            self.app, commands.verb(*self.listing.path), self.values(), quiet=True
        )
        table = outcome.table()
        self.problem = "" if outcome.ok else outcome.problem
        self.rows = list(table.rows) if table is not None else []
        if table is not None:
            self._show(table)

    def _show(self, table: Table) -> None:
        headers = table.headers()
        kept = [
            index
            for index, header in enumerate(headers)
            if header not in HIDDEN_COLUMNS
        ]
        self.view.columns = [Column(headers[index].capitalize()) for index in kept]
        shown = []
        for row, cells in zip(table.rows, table.cells()):
            texts, tones = [], []
            for index in kept:
                cell, tone = moment(cells[index]), ""
                if headers[index] in STATE_COLUMNS and cell in STATES:
                    cell, tone = state(self.app.glyphs, cell)
                texts.append(cell)
                tones.append(tone)
            shown.append(Row(texts, row, tones))
        self.view.show(shown)

    def resumed(self) -> None:
        self.load()

    def adds(self) -> list[Action]:
        return [action for action in self.listing.adds if allowed(self.app, action)]

    def draw(self, canvas: Canvas, area: Area) -> None:
        if self.problem:
            layout.notice(
                canvas, area.row(0), self.app.glyphs, theme.DANGER, self.problem
            )
            area = area.inset(top=2)
        self.view.draw(canvas, area, self.app.glyphs, not self.app.in_sidebar)
        return None

    def key(self, key: Key) -> bool:
        if self.view.filtering:
            return self.view.key(key)
        row = self.view.selected
        if key.name == "enter" and row is not None:
            self.open(row.data)
        elif key.is_text() and key.text == "a" and self.adds():
            self.add()
        elif key.is_text() and key.text == "r":
            self.load()
        else:
            return self.view.key(key)
        return True

    def open(self, row: Mapping[str, Any]) -> None:
        subject = ObjectScreen(self.app, self.listing, row, self.rows, self.parent)
        if self.listing.straight:
            subject.act(subject.actions()[0])
        else:
            self.app.push(subject)

    def add(self) -> None:
        offered = self.adds()
        chosen = offered[0]
        if len(offered) > 1:
            chosen = self.app.modal(
                Pick("Add", [Choice(action.label, action) for action in offered])
            )
        if chosen is not None:
            perform(self.app, chosen, {}, [], self.parent)

    def hints(self) -> Sequence[tuple[str, str]]:
        pairs = [("↑↓", "Move"), ("Enter", "Open")]
        if self.adds():
            pairs.append(
                ("a", self.adds()[0].label if len(self.adds()) == 1 else "Add")
            )
        return (*pairs, ("r", "Refresh"), ("/", "Filter"))


def filled(
    action: Action,
    row: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    parent: str,
) -> dict:
    values: dict[str, Any] = {}
    for key, source in action.fill.items():
        if source == sections.REFERENCE:
            values[key] = pickers.reference(row, rows)
        elif source == sections.REFERENCES:
            values[key] = [pickers.reference(row, rows)]
        elif source == sections.IDENTIFIER:
            values[key] = str(row["id"])
        elif source == sections.PARENT:
            values[key] = parent
        elif source == sections.PARENTS:
            values[key] = [parent]
    return values


def perform(
    app: Any,
    action: Action,
    row: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    parent: str,
) -> Optional[Any]:
    values = filled(action, row, rows, parent)
    verb = commands.verb(*action.path)
    if action.direct:
        return forms.launch(app, verb, values, action.label)
    app.push(forms.FormScreen(app, verb, values, action.label, fixed=list(values)))
    return None


class ObjectScreen(Screen):
    def __init__(
        self,
        app: Any,
        listing: Listing,
        row: Mapping[str, Any],
        rows: Sequence[Mapping[str, Any]],
        parent: str = "",
    ) -> None:
        super().__init__(app)
        self.listing = listing
        self.row = row
        self.rows = rows
        self.parent = parent
        self.title = str(row.get(listing.named) or row.get("id") or listing.title)
        self.view = ListView(columns=(Column(""), Column("")), yields=1)
        self.view.show(
            [
                Row((action.label, action.detail), action, danger=action.danger)
                for action in self.actions()
            ]
        )

    @property
    def reference(self) -> str:
        return pickers.reference(self.row, self.rows)

    def actions(self) -> list[Action]:
        return [action for action in self.listing.actions if allowed(self.app, action)]

    def resumed(self) -> None:
        try:
            rows = pickers.rows(
                self.app,
                self.listing.path,
                {key: self.parent for key in self.listing.fill},
            )
        except LookupError:
            return
        mine = [row for row in rows if str(row.get("id")) == str(self.row.get("id"))]
        if not mine:
            if self in self.app.stack:
                self.app.stack.remove(self)
                self.app.top.resumed()
            return
        self.row, self.rows = mine[0], rows
        self.title = str(
            self.row.get(self.listing.named) or self.row.get("id") or self.title
        )

    def draw(self, canvas: Canvas, area: Area) -> None:
        self.view.draw(canvas, area, self.app.glyphs, not self.app.in_sidebar)
        return None

    def key(self, key: Key) -> bool:
        row = self.view.selected
        if key.name == "enter" and row is not None:
            self.act(row.data)
            return True
        return self.view.key(key)

    def act(self, action: Action) -> None:
        if action.listing:
            self.app.push(
                ListingScreen(
                    self.app,
                    sections.LISTINGS[action.listing],
                    self.reference,
                    self.title,
                )
            )
        elif action.opens == sections.FILES:
            self.app.push(FilesScreen(self.app, self.reference, self.title))
        elif action.opens == sections.FOLDERS:
            self.app.push(FoldersScreen(self.app, self.reference, self.title))
        else:
            outcome = perform(self.app, action, self.row, self.rows, self.parent)
            if (
                outcome is not None
                and outcome.ok
                and action.leaves
                and self in self.app.stack
            ):
                self.app.stack.remove(self)

    def hints(self) -> Sequence[tuple[str, str]]:
        return (("↑↓", "Move"), ("Enter", "Do it"))


class FilesScreen(Screen):
    def __init__(self, app: Any, reference: str, name: str) -> None:
        super().__init__(app)
        self.title = "Files"
        self.reference = reference
        self.explorer = Explorer(app, ApplicationFiles(app, reference, name))
        self.downloads = permissions.can(app.user, Capability.FILES_DOWNLOAD)
        self.changes = permissions.can(app.user, Capability.FILES_CHANGE)

    def draw(self, canvas: Canvas, area: Area) -> None:
        self.explorer.draw(canvas, area, not self.app.in_sidebar)
        return None

    def key(self, key: Key) -> bool:
        if self.explorer.view.filtering or not key.is_text():
            return self.explorer.key(key)
        if key.text == "d" and self.downloads:
            self.download()
        elif key.text == "u" and self.changes:
            self.upload()
        elif key.text == "n" and self.changes:
            self.new_folder()
        elif key.text == "x" and self.changes:
            self.delete()
        else:
            return self.explorer.key(key)
        return True

    def _run(self, name: str, values: dict, label: str) -> None:
        forms.launch(
            self.app,
            commands.verb("files", name),
            {"<application>": self.reference, **values},
            label,
        )

    def resumed(self) -> None:
        self.explorer.refresh()

    def download(self) -> None:
        chosen = self.explorer.selected
        if chosen is None or chosen.kind != FILE:
            self.app.say("Select a file to download.")
            return
        target = self.app.modal(
            PathDialog(
                self.app,
                LocalDisk(),
                PICK_TARGET,
                f"Where to save {text.safe(chosen.name)}",
            )
        )
        if target:
            self._run(
                "download", {"<path>": chosen.path, "--output": target}, "Download"
            )

    def upload(self) -> None:
        source = self.app.modal(
            PathDialog(self.app, LocalDisk(), PICK_FILE, "Choose the file to upload")
        )
        if source:
            self._run(
                "upload", {"<folder>": self.explorer.path, "<file>": source}, "Upload"
            )

    def new_folder(self) -> None:
        name = self.app.modal(Ask("New folder", f"It is made in {self.explorer.path}."))
        if name:
            self._run(
                "mkdir", {"<folder>": self.explorer.path, "<name>": name}, "New folder"
            )

    def delete(self) -> None:
        chosen = self.explorer.selected
        if chosen is None:
            return
        self._run("delete", {"<path>": chosen.path}, "Delete")

    def hints(self) -> Sequence[tuple[str, str]]:
        pairs = [("Enter", "Open"), ("Backspace", "Up")]
        if self.downloads:
            pairs.append(("d", "Download"))
        if self.changes:
            pairs += [("u", "Upload"), ("n", "New folder"), ("x", "Delete")]
        return (*pairs, ("g", "Go to"), ("r", "Refresh"))


class FoldersScreen(Screen):
    def __init__(self, app: Any, reference: str, name: str) -> None:
        super().__init__(app)
        self.title = "Folders"
        self.reference = reference
        self.explorer = Explorer(app, ServerFolders(app, reference, name))
        self.adds = permissions.can(app.user, Capability.APPLICATIONS_MANAGE)

    def draw(self, canvas: Canvas, area: Area) -> None:
        self.explorer.draw(canvas, area, not self.app.in_sidebar)
        return None

    def key(self, key: Key) -> bool:
        if (
            key.is_text()
            and key.text == "a"
            and self.adds
            and not self.explorer.view.filtering
        ):
            values = {"--server": self.reference, "--folder": self.explorer.path}
            self.app.push(
                forms.FormScreen(
                    self.app,
                    commands.verb("app", "add"),
                    values,
                    "Add an application",
                    fixed=["--server"],
                )
            )
            return True
        return self.explorer.key(key)

    def hints(self) -> Sequence[tuple[str, str]]:
        pairs = [("Enter", "Open"), ("Backspace", "Up")]
        if self.adds:
            pairs.append(("a", "Add the application in this folder"))
        return (*pairs, ("g", "Go to"), ("r", "Refresh"))
