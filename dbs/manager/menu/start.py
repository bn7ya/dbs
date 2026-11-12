from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from django.contrib.auth import get_user_model

from dbs.manager import permissions
from dbs.manager.adapters import accounts

from .app import App, Screen, Section
from .kit.dialogs import Choice, Pick
from .kit.logo import Logo, outlines
from .screens.accounts import AccountsScreen, first_account
from .screens.catalogue import CatalogueScreen
from .screens.home import DashboardScreen
from .screens.listing import ListingScreen
from .screens.manager import ManagerScreen
from .screens.sections import LISTINGS

LOGO_FILE = Path(__file__).resolve().parents[2] / "static" / "dbs" / "logo.svg"


def logo() -> Optional[Logo]:
    try:
        return outlines(LOGO_FILE.read_text(encoding="utf-8"))
    except (OSError, AttributeError, ValueError):
        return None


def sections() -> list[Section]:
    return [
        Section("Dashboard", DashboardScreen),
        Section("Servers", lambda app: ListingScreen(app, LISTINGS["servers"])),
        Section(
            "Applications", lambda app: ListingScreen(app, LISTINGS["applications"])
        ),
        Section("Backups", lambda app: ListingScreen(app, LISTINGS["backups"])),
        Section("Activity", lambda app: ListingScreen(app, LISTINGS["activity"])),
        Section("Accounts", AccountsScreen),
        Section("Manager", ManagerScreen),
        Section("All commands", CatalogueScreen),
    ]


def started(app: App, account: Optional[str]) -> int:
    chosen = accounts.acting(account) if account else None
    app.terminal.enter()
    try:
        with app.capturing():
            return session(app, chosen)
    finally:
        app.terminal.leave()


def session(app: App, chosen: Any = None) -> int:
    user = chosen or who(app)
    if user is None:
        return 0
    act_as(app, user)
    app.loop()
    return 0


def act_as(app: App, user: Any) -> None:
    app.user = user
    app.account = (
        f"{user.get_username()} {app.glyphs.middle} {permissions.role_of(user)}"
    )
    app.switch = (lambda: switch(app)) if len(active()) > 1 else None
    app.use(sections())
    warning = accounts.expiry_warning(user)
    if warning:
        app.say(warning.replace("Warning: ", ""), "warning")


def active() -> list:
    return list(get_user_model().objects.filter(is_active=True).order_by("username"))


def who(app: App) -> Any:
    app.stack = [Screen(app)]
    found = active()
    if not found:
        return first_account(app)
    if len(found) == 1:
        return found[0]
    return app.modal(
        Pick(
            "Act as which account?",
            [
                Choice(user.get_username(), user, str(permissions.role_of(user)))
                for user in found
            ],
        )
    )


def switch(app: App) -> None:
    user = app.modal(
        Pick(
            "Act as which account?",
            [
                Choice(user.get_username(), user, str(permissions.role_of(user)))
                for user in active()
            ],
        )
    )
    if user is not None:
        act_as(app, user)
