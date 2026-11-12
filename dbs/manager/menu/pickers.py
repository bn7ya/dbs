from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Optional

from dbs.manager.terminal.output import text

from . import commands, meanings, running
from .commands import Argument, Verb
from .explorer import PICK_ANY, PICK_FILE, PICK_FOLDER, PICK_TARGET, PathDialog
from .kit.dialogs import Choice, Pick
from .sources import ApplicationFiles, LocalDisk, ServerFolders

ACTIVITY_SHOWN = "50"
NOTHING = object()


def rows(
    app: Any, path: Sequence[str], values: Optional[Mapping[str, Any]] = None
) -> list[dict]:
    outcome = running.run(app, commands.verb(*path), values or {}, quiet=True)
    table = outcome.table()
    if not outcome.ok:
        raise LookupError(outcome.problem or "the list could not be read.")
    return list(table.rows) if table is not None else []


def reference(row: Mapping[str, Any], among: Sequence[Mapping[str, Any]]) -> str:
    name = row.get("name")
    same = [other for other in among if other.get("name") == name]
    return str(name) if name and len(same) == 1 else str(row["id"])


def pick(app: Any, verb: Verb, argument: Argument, values: Mapping[str, Any]) -> Any:
    meaning = meanings.meaning(verb, argument)
    owner = values.get(meaning.of) if meaning.of else None
    try:
        return PICKERS[meaning.kind](app, argument, values, owner)
    except LookupError as exc:
        app.tell(argument.label, str(exc))
        return NOTHING


def can_pick(verb: Verb, argument: Argument) -> bool:
    return meanings.meaning(verb, argument).kind in PICKERS


def _one(app: Any, title: str, choices: Sequence[Choice], current: Any = None) -> Any:
    chosen = app.modal(Pick(title, choices, chosen=[current] if current else ()))
    return NOTHING if chosen is None else chosen


def _servers(app: Any) -> list[Choice]:
    found = rows(app, ("server", "list"))
    return [
        Choice(row["name"], reference(row, found), f"{row['username']}@{row['host']}")
        for row in found
    ]


def _applications(app: Any) -> list[Choice]:
    found = rows(app, ("app", "list"))
    return [
        Choice(row["name"], reference(row, found), f"on {row['server']['name']}")
        for row in found
    ]


def _server(app, argument, values, owner):
    return _one(app, "Choose a server", _servers(app), values.get(argument.key))


def _application(app, argument, values, owner):
    return _one(
        app, "Choose an application", _applications(app), values.get(argument.key)
    )


def _many(app: Any, title: str, choices: Sequence[Choice], current: Any) -> Any:
    chosen = app.modal(Pick(title, choices, many=True, chosen=current or ()))
    return NOTHING if chosen is None else chosen


def _server_list(app, argument, values, owner):
    return _many(app, "Choose servers", _servers(app), values.get(argument.key))


def _application_list(app, argument, values, owner):
    return _many(
        app, "Choose applications", _applications(app), values.get(argument.key)
    )


def _backup(app, argument, values, owner):
    within = values.get("<application>") or values.get("--from")
    found = rows(app, ("backup", "list"), {"--app": within} if within else {})
    choices = [
        Choice(
            row["name"],
            str(row["id"]),
            f"{text(row.get('application_name'))}, {text(row.get('validation'))}",
        )
        for row in found
    ]
    return _one(app, "Choose a backup", choices, values.get(argument.key))


def _plan(app, argument, values, owner):
    found = rows(app, ("plan", "list"))
    choices = [
        Choice(row["name"], str(row["id"]), text(row.get("application_name")))
        for row in found
    ]
    return _one(app, "Choose a plan", choices, values.get(argument.key))


def _version(app, argument, values, owner):
    application = owner or values.get("<application>")
    if not application:
        application = _application(app, argument, {}, None)
        if application is NOTHING:
            return NOTHING
    found = rows(app, ("env", "list"), {"<application>": application})
    choices = [
        Choice(
            str(row["created_at"]),
            str(row["id"]),
            f"{row['source']}, {row['size']} bytes",
        )
        for row in found
    ]
    return _one(
        app, "Choose a version of the .env file", choices, values.get(argument.key)
    )


def _activity(app, argument, values, owner):
    found = rows(app, ("activity", "list"), {"--limit": ACTIVITY_SHOWN})
    choices = [
        Choice(
            f"{row['id']}  {row['action']}",
            str(row["id"]),
            f"{row['status']}, {text(row.get('application_name') or row.get('server_name'))}",
        )
        for row in found
    ]
    return _one(app, "Choose an entry", choices, values.get(argument.key))


def _account(app, argument, values, owner):
    from dbs.manager.accounts.services import AccountManagementService

    choices = [
        Choice(account.user.get_username(), account.user.get_username(), account.role)
        for account in AccountManagementService(None).list()
    ]
    return _one(app, "Choose an account", choices, values.get(argument.key))


def _path(app: Any, source: Any, mode: str, title: str, start: Any = None) -> Any:
    chosen = app.modal(PathDialog(app, source, mode, title, start or None))
    return NOTHING if chosen is None else chosen


def _local_file(app, argument, values, owner):
    return _path(app, LocalDisk(), PICK_FILE, "Choose a file on this computer")


def _local_target(app, argument, values, owner):
    return _path(app, LocalDisk(), PICK_TARGET, "Where to write it on this computer")


def _server_folder(app, argument, values, owner):
    if not owner:
        raise LookupError("Choose the server first.")
    return _path(
        app,
        ServerFolders(app, owner, str(owner)),
        PICK_FOLDER,
        "Choose a folder on the server",
        values.get(argument.key),
    )


def _application_path(app, argument, values, owner):
    if not owner:
        raise LookupError("Choose the application first.")
    return _path(
        app,
        ApplicationFiles(app, owner, str(owner)),
        PICK_ANY,
        "Choose a file or folder",
    )


def _application_folder(app, argument, values, owner):
    if not owner:
        raise LookupError("Choose the application first.")
    return _path(
        app, ApplicationFiles(app, owner, str(owner)), PICK_FOLDER, "Choose a folder"
    )


PICKERS = {
    meanings.SERVER: _server,
    meanings.SERVERS: _server_list,
    meanings.APPLICATION: _application,
    meanings.APPLICATIONS: _application_list,
    meanings.BACKUP: _backup,
    meanings.PLAN: _plan,
    meanings.VERSION: _version,
    meanings.ACTIVITY: _activity,
    meanings.ACCOUNT: _account,
    meanings.LOCAL_FILE: _local_file,
    meanings.LOCAL_TARGET: _local_target,
    meanings.SERVER_FOLDER: _server_folder,
    meanings.APPLICATION_PATH: _application_path,
    meanings.APPLICATION_FOLDER: _application_folder,
}
