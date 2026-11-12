from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from dbs.manager import conf, keystore, paths
from dbs.manager.dashboard.services import DashboardService

from .. import commands, forms
from ..app import Screen
from ..kit import layout, theme
from ..kit.canvas import Area, Canvas
from ..kit.keys import Key
from ..kit.lists import Column, ListView, Row
from .home import ago

LOGO_COLUMNS = 36
LOGO_ROWS = 14
RUN = "Start the manager in the browser"
EXPORT = "Export the manager's data to one file"
IMPORT = "Load an export"
CLAUDE = "Let Claude drive the manager"
ACCOUNT = "Act as another account"


class ManagerScreen(Screen):
    title = "Manager"

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self.view = ListView(columns=(Column(""), Column("")), yields=1)
        self.facts: list[tuple[str, str]] = []
        self.load()

    def load(self) -> None:
        about = DashboardService(self.app.user).about()
        folder = conf.data_dir()
        self.facts = [
            ("Version", str(about["version"])),
            ("Data folder", about["data_dir"]),
            ("Database", about["database"]),
            ("Backups", about["backups_dir"]),
            ("Secret key", keystore.location(folder)),
            ("Log", str(paths.log_path(folder))),
            ("Last export", ago(about["last_export_at"])),
        ]
        rows = [
            Row((RUN, "It stops with Ctrl+C and brings you back here."), ("run",)),
            Row(
                (EXPORT, "Keep the file and its passphrase somewhere else."),
                ("export",),
            ),
            Row((IMPORT, ""), ("import",)),
            Row((CLAUDE, ""), ("mcp",)),
        ]
        if self.app.switch is not None:
            rows.append(Row((ACCOUNT, ""), None))
        self.view.show(rows)

    def resumed(self) -> None:
        self.load()

    def draw(self, canvas: Canvas, area: Area) -> None:
        y = area.y
        wide = (
            self.app.logo is not None
            and area.columns >= LOGO_COLUMNS + 44
            and area.rows >= LOGO_ROWS + 8
        )
        if wide:
            layout.logo(
                canvas,
                area.right - LOGO_COLUMNS,
                y,
                self.app.logo,
                LOGO_COLUMNS,
                self.app.colours,
            )
        width = max(len(label) for label, _ in self.facts)
        room = area.columns - (LOGO_COLUMNS + 2 if wide else 0)
        for label, value in self.facts:
            canvas.put(area.x, y, f"{label:<{width}}", theme.MUTED)
            canvas.put(area.x + width + 2, y, value, theme.BASE, room - width - 2)
            y += 1
        top = max(y + 1, area.y + LOGO_ROWS + 1) if wide else y + 1
        self.view.draw(
            canvas,
            Area(area.x, top, area.columns, area.bottom - top),
            self.app.glyphs,
            not self.app.in_sidebar,
        )
        return None

    def key(self, key: Key) -> bool:
        row = self.view.selected
        if key.name != "enter" or row is None:
            return self.view.key(key)
        if row.data is None:
            self.app.switch()
            return True
        verb = commands.verb(*row.data)
        if row.data == ("mcp",) or row.data == ("import",):
            forms.launch(self.app, verb, {})
        else:
            self.app.push(forms.FormScreen(self.app, verb, title=str(row.cells[0])))
        return True

    def hints(self) -> Sequence[tuple[str, str]]:
        return (("↑↓", "Move"), ("Enter", "Do it"))
