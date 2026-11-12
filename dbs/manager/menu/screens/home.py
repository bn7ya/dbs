from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from typing import Any, Optional

from django.utils import timezone

from dbs.manager import permissions
from dbs.manager.dashboard.services import DashboardService
from dbs.manager.permissions import Capability

from .. import commands, forms
from ..app import Screen
from ..explorer import size
from ..kit import layout, theme
from ..kit.canvas import Area, Canvas
from ..kit.keys import Key
from ..kit.lists import Column, ListView, Row
from .listing import STATES, ObjectScreen, state
from .sections import LISTINGS

EXPORT_EVERY = timedelta(days=7)
CONNECTIONS = {
    "online": (theme.SUCCESS, "Online"),
    "offline": (theme.DANGER, "Offline"),
    "unknown": (theme.NEUTRAL, "Not seen yet"),
}
STEPS = ((86400, "d"), (3600, "h"), (60, "min"))


def ago(when: Any) -> str:
    if when is None:
        return "never"
    seconds = int((timezone.now() - when).total_seconds())
    ahead = seconds < 0
    seconds = abs(seconds)
    for length, unit in STEPS:
        if seconds >= length:
            amount = f"{seconds // length} {unit}"
            return f"in {amount}" if ahead else f"{amount} ago"
    return "soon" if ahead else "just now"


class DashboardScreen(Screen):
    title = "Dashboard"

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self.view = ListView(
            columns=(
                Column("Name"),
                Column("Where"),
                Column("State"),
                Column("Last backup"),
                Column("Next run"),
            ),
            empty="No servers yet. Add a server, then the applications it runs.",
            yields=1,
        )
        self.totals: list[tuple[str, str]] = []
        self.warnings: list[str] = []
        self.servers: list[dict] = []
        self.applications: list[dict] = []
        self.load()

    def load(self) -> None:
        summary = DashboardService(self.app.user).summary()
        self.servers = summary["servers"]
        self.applications = [
            item for server in self.servers for item in server["applications"]
        ]
        failures = sum(item["failures_7d"] for item in self.applications)
        self.totals = [
            ("Servers", str(len(self.servers))),
            ("Applications", str(len(self.applications))),
            ("Stored here", size(summary["storage_bytes"])),
            ("Failures in 7 days", str(failures)),
            ("Last export", ago(summary["last_export_at"])),
        ]
        self.warnings = self._warnings(summary)
        rows = []
        for server in self.servers:
            rows.append(self._server(server))
            rows += [self._application(item) for item in server["applications"]]
        self.view.show(rows)

    def _warnings(self, summary: dict) -> list[str]:
        found = []
        exported = summary["last_export_at"]
        if self.servers and (
            exported is None or timezone.now() - exported > EXPORT_EVERY
        ):
            found.append("Export the manager's data: open Manager, then Export.")
        disk = summary.get("disk")
        if disk and disk.get("low"):
            found.append(
                f"The disk that holds the backups is nearly full: {size(disk['free_bytes'])} free."
            )
        return found

    def _server(self, server: dict) -> Row:
        glyphs = self.app.glyphs
        tone, word = CONNECTIONS.get(server["connection_state"], CONNECTIONS["unknown"])
        return Row(
            (
                server["name"],
                server["host"],
                f"{theme.symbol(glyphs, tone)} {word}",
                "",
                "",
            ),
            ("servers", server),
            ("", "", tone),
        )

    def _application(self, item: dict) -> Row:
        glyphs = self.app.glyphs
        check, check_tone = _state(glyphs, item["check_status"])
        backup = item["last_backup"]
        last, last_tone = "none yet", ""
        if backup:
            last = ago(backup["created_at"])
            if backup["validation"] in STATES:
                word, last_tone = state(glyphs, backup["validation"])
                last = f"{last}, {word}"
        following = ago(item["next_plan_run"]) if item["next_plan_run"] else "no plan"
        return Row(
            (f"  {item['name']}", _where(item), check, last, following),
            ("applications", item),
            ("", "", check_tone, last_tone),
        )

    def resumed(self) -> None:
        self.load()

    def draw(self, canvas: Canvas, area: Area) -> None:
        x = area.x
        for label, value in self.totals:
            if x + len(label) + len(value) + 1 > area.right:
                break
            x = canvas.put(x, area.y, label, theme.MUTED)
            x = canvas.put(x + 1, area.y, value, theme.HEADING) + 3
        y = area.y + 2
        for warning in self.warnings:
            layout.notice(
                canvas,
                Area(area.x, y, area.columns, 1),
                self.app.glyphs,
                theme.WARNING,
                warning,
            )
            y += 2
        y = min(y, area.bottom)
        self.view.draw(
            canvas,
            Area(area.x, y, area.columns, area.bottom - y),
            self.app.glyphs,
            not self.app.in_sidebar,
        )
        return None

    def key(self, key: Key) -> bool:
        row = self.view.selected
        if key.name == "enter" and row is not None:
            kind, item = row.data
            among = self.servers if kind == "servers" else self.applications
            self.app.push(ObjectScreen(self.app, LISTINGS[kind], item, among))
        elif key.is_text() and key.text == "a" and self._adds():
            self.app.push(
                forms.FormScreen(
                    self.app, commands.verb("server", "add"), title="Add a server"
                )
            )
        elif key.is_text() and key.text == "r":
            self.load()
        else:
            return self.view.key(key)
        return True

    def _adds(self) -> bool:
        return permissions.can(self.app.user, Capability.SERVERS_MANAGE)

    def hints(self) -> Sequence[tuple[str, str]]:
        pairs = [("↑↓", "Move"), ("Enter", "Open")]
        if self._adds():
            pairs.append(("a", "Add a server"))
        return (*pairs, ("r", "Refresh"))


def _where(item: dict) -> str:
    if item["kind"] == "host":
        return "on the server"
    return " ".join(part for part in (item.get("engine"), item["kind"]) if part)


def _state(glyphs: Any, value: Optional[str]) -> tuple[str, str]:
    return state(glyphs, value if value in STATES else "unknown")
