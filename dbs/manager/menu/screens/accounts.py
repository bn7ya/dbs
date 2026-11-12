from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Optional

from rest_framework.exceptions import APIException

from dbs.manager.accounts.services import AccountManagementService
from dbs.manager.accounts.services.account_service import password_max_age
from dbs.manager.adapters import AdapterError, accounts
from dbs.manager.adapters.problems import problem

from ..app import Screen
from ..kit import layout, theme
from ..kit.canvas import Area, Canvas
from ..kit.dialogs import Ask, Choice, Confirm, Pick
from ..kit.keys import Key
from ..kit.lists import Column, ListView, Row

LOGO_COLUMNS = 36
LOGO_ROWS = 14
ROLES = ("admin", "operator", "viewer")
ROLE_NOTES = {
    "admin": "Changes servers, applications and plans; restores and deploys.",
    "operator": "Takes and verifies backups, runs plans, rehearses.",
    "viewer": "Looks, and changes nothing.",
    "master": "Everything, and the accounts. Giving it away hands the role over.",
}
FIRST = (
    "The manager has no account yet. The first one is the master account: it can do "
    "everything, and it adds the other accounts. Choose its name."
)


def refusal(exc: Exception) -> str:
    message = problem(exc) if isinstance(exc, APIException) else str(exc)
    return message[:1].upper() + message[1:]


def new_password(app: Any, name: str, low: bool = False) -> Optional[str]:
    return app.modal(
        lowered(
            Ask(f"Password for {name}", "It lasts 30 days.", masked=True, twice=True),
            low,
        )
    )


def lowered(dialog: Any, low: bool = True) -> Any:
    dialog.low = low
    return dialog


def first_account(app: Any) -> Any:
    app.stack = [WelcomeScreen(app)]
    while True:
        name = app.modal(lowered(Ask("The first account", FIRST)))
        if not name:
            return None
        password = new_password(app, name, low=True)
        if not password:
            continue
        try:
            account = AccountManagementService(None).create(
                username=name, password=password, role="master"
            )
        except APIException as exc:
            app.tell("That did not work", refusal(exc), theme.DANGER)
            continue
        return account.user


class WelcomeScreen(Screen):
    def draw(self, canvas: Canvas, area: Area) -> None:
        canvas.put(
            area.x, area.y, "Welcome to the DBS manager.", theme.HEADING, area.columns
        )
        if (
            self.app.logo is not None
            and area.columns >= LOGO_COLUMNS
            and area.rows >= LOGO_ROWS + 14
        ):
            x = area.x + (area.columns - LOGO_COLUMNS) // 2
            layout.logo(
                canvas, x, area.y + 2, self.app.logo, LOGO_COLUMNS, self.app.colours
            )
        return None


class AccountsScreen(Screen):
    title = "Accounts"

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self.view = ListView(
            columns=(
                Column("Name"),
                Column("Role"),
                Column("Can sign in"),
                Column("Two-factor"),
                Column("Password expires"),
            )
        )
        self.service = AccountManagementService(None)
        self.load()

    def load(self) -> None:
        rows = []
        for account in self.service.list():
            expires = account.password_changed_at + password_max_age()
            rows.append(
                Row(
                    (
                        account.user.get_username(),
                        account.role,
                        "yes" if account.user.is_active else "no",
                        "yes" if account.has_two_factor else "no",
                        f"{expires:%Y-%m-%d}",
                    ),
                    account,
                    muted=not account.user.is_active,
                )
            )
        self.view.show(rows)

    def resumed(self) -> None:
        self.load()

    def draw(self, canvas: Canvas, area: Area) -> None:
        note = (
            "Whoever can open this computer's data folder can change the accounts here, "
            "as with the commands."
        )
        used = layout.paragraph(
            canvas, Area(area.x, area.y, area.columns, 2), note, theme.MUTED
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
            self.change(row.data)
        elif key.is_text() and key.text == "a":
            self.add()
        else:
            return self.view.key(key)
        return True

    def attempt(self, done: str, change: Any) -> None:
        try:
            change()
        except (APIException, AdapterError) as exc:
            self.app.tell("That did not work", refusal(exc), theme.DANGER)
        else:
            self.app.say(done, theme.SUCCESS)
        self.load()

    def add(self) -> None:
        name = self.app.modal(Ask("Add an account", "Its name, as it will sign in."))
        if not name:
            return
        role = self.app.modal(
            Pick(
                "What it may do",
                [Choice(role, role, ROLE_NOTES[role]) for role in ROLES],
            )
        )
        if role is None:
            return
        password = new_password(self.app, name)
        if not password:
            return
        self.attempt(
            f"Added {name} as {role}. It sets up two-factor sign-in and chooses its own "
            "password the first time it signs in.",
            lambda: self.service.create(username=name, password=password, role=role),
        )

    def change(self, account: Any) -> None:
        name = account.user.get_username()
        active = account.user.is_active
        choices = [
            Choice("Set a new password", self.password),
            Choice("Change its role", self.role),
            Choice(
                "Stop it signing in" if active else "Let it sign in again",
                self.switch,
                danger=active,
            ),
            Choice("Forget its two-factor sign-in", self.forget, danger=True),
        ]
        chosen = self.app.modal(Pick(name, choices))
        if chosen is not None:
            chosen(account)

    def password(self, account: Any) -> None:
        name = account.user.get_username()
        password = new_password(self.app, name)
        if password:
            self.attempt(
                f"Changed the password of {name}; it lasts 30 days.",
                lambda: accounts.set_password(accounts.named(name), password),
            )

    def role(self, account: Any) -> None:
        name = account.user.get_username()
        choices = [Choice(role, role, ROLE_NOTES[role]) for role in (*ROLES, "master")]
        role = self.app.modal(Pick(f"Role of {name}", choices, chosen=[account.role]))
        if role is None or role == account.role:
            return
        if role == "master":
            question = f"Hand the master role over to {name}? The master account of now becomes an admin."
            if not self.app.modal(Confirm("Hand over", question, danger=True)):
                return
            self.attempt(
                f"{name} is now the master account.",
                lambda: self.service.make_master(account.pk),
            )
        else:
            self.attempt(
                f"{name} is now {role}.",
                lambda: self.service.set_role(account.pk, role),
            )

    def switch(self, account: Any) -> None:
        name = account.user.get_username()
        if account.user.is_active:
            if not self.app.modal(
                Confirm(
                    "Stop it signing in", f"Stop {name} from signing in?", danger=True
                )
            ):
                return
            self.attempt(
                f"{name} can no longer sign in.",
                lambda: self.service.set_active(account.pk, False),
            )
        else:
            self.attempt(
                f"{name} can sign in again.",
                lambda: self.service.set_active(account.pk, True),
            )

    def forget(self, account: Any) -> None:
        name = account.user.get_username()
        question = f"Forget the authenticator and recovery codes of {name}? It sets them up again at its next sign-in."
        if self.app.modal(Confirm("Forget two-factor", question, danger=True)):
            self.attempt(
                f"Forgot the two-factor sign-in of {name}.",
                lambda: self.service.reset_two_factor(account.pk),
            )

    def hints(self) -> Sequence[tuple[str, str]]:
        return (
            ("↑↓", "Move"),
            ("Enter", "Change"),
            ("a", "Add an account"),
            ("/", "Filter"),
        )
