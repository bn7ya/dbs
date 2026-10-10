from __future__ import annotations

import argparse
from collections.abc import Callable

RESTORE_MODES = ("merge", "replace")
PLAN_KINDS = ("dbs", "archive", "collect")
ACTIVITY_STATUSES = ("queued", "running", "succeeded", "failed")
ACTIVITY_LIMIT = 20

Location = Callable[[argparse.ArgumentParser], None]


def register(commands, location: Location) -> None:
    for build in (servers, backups, plans, activity, envfiles, files, redeploy):
        build(commands, location)


def _area(commands, name: str, help_text: str):
    area = commands.add_parser(name, help=help_text, description=help_text)
    return area.add_subparsers(dest="verb", metavar="VERB", required=True)


def _verb(verbs, name: str, help_text: str, handler: str, location: Location):
    verb = verbs.add_parser(name, help=help_text, description=help_text)
    verb.set_defaults(handler=handler)
    location(verb)
    verb.add_argument(
        "--as",
        dest="account",
        metavar="NAME",
        help="The account to act as. Defaults to the only account.",
    )
    verb.add_argument(
        "--json", action="store_true", help="Print what the web API would return."
    )
    verb.add_argument(
        "--password-stdin",
        action="store_true",
        help="Read your account password from stdin when an action asks for it.",
    )
    return verb


def _yes(parser) -> None:
    parser.add_argument(
        "--yes", action="store_true", help="Do not ask for confirmation."
    )


def _server_settings(parser) -> None:
    parser.add_argument("--project-dir", help="The folder that holds manage.py.")
    parser.add_argument("--python", dest="python_path", help="The Python to run.")
    parser.add_argument("--manage", dest="manage_path", help="The manage.py to run.")
    parser.add_argument(
        "--settings", dest="settings_module", help="DJANGO_SETTINGS_MODULE to use."
    )
    parser.add_argument(
        "--backup-dir",
        dest="remote_backup_dir",
        help="Where the server writes its backups.",
    )
    parser.add_argument("--env-path", help="The .env file to keep versions of.")
    parser.add_argument(
        "--file-root",
        dest="file_roots",
        action="append",
        metavar="PATH",
        help="A folder the Files page may open. Repeat for more.",
    )


def _ssh_auth(parser):
    auth = parser.add_mutually_exclusive_group()
    auth.add_argument("--key-file", help="A private key file this server accepts.")
    auth.add_argument(
        "--ssh-password",
        action="store_true",
        help="Ask for the SSH password.",
    )
    auth.add_argument(
        "--ssh-password-stdin",
        action="store_true",
        help="Read the SSH password from stdin.",
    )
    parser.add_argument(
        "--key-passphrase",
        action="store_true",
        help="Ask for the passphrase that unlocks --key-file.",
    )
    return auth


def servers(commands, location: Location) -> None:
    verbs = _area(commands, "server", "Add, change, check and remove servers.")

    found = _verb(verbs, "list", "List the servers.", "servers:list_servers", location)
    found.add_argument("--search", help="Only servers whose name or host has this.")

    show = _verb(verbs, "show", "Show one server.", "servers:show", location)
    show.add_argument("server", help="The server's name or id.")

    add = _verb(
        verbs,
        "add",
        "Add a server: confirm its host key, find its project, and check it.",
        "servers:add",
        location,
    )
    add.add_argument("name", help="A name for this server.")
    add.add_argument("--host", required=True, help="Its address.")
    add.add_argument("--port", type=int, default=None, help="Its SSH port.")
    add.add_argument("--user", dest="username", required=True, help="The SSH account.")
    _ssh_auth(add).add_argument(
        "--generate-key",
        action="store_true",
        help="Make a new key pair and print the line to add to authorized_keys.",
    )
    add.add_argument(
        "--host-key", help="The host key to pin, instead of confirming the one offered."
    )
    add.add_argument(
        "--backup-passphrase",
        action="store_true",
        help="Ask for the passphrase its backups use. Defaults to a new random one.",
    )
    add.add_argument(
        "--no-discover",
        action="store_true",
        help="Do not look for the project and its Python.",
    )
    _server_settings(add)
    _yes(add)

    edit = _verb(verbs, "edit", "Change a server's settings.", "servers:edit", location)
    edit.add_argument("server", help="The server's name or id.")
    edit.add_argument("--name", help="A new name.")
    edit.add_argument("--host", help="A new address.")
    edit.add_argument("--port", type=int, help="A new SSH port.")
    edit.add_argument("--user", dest="username", help="A new SSH account.")
    _ssh_auth(edit)
    edit.add_argument(
        "--backup-passphrase",
        action="store_true",
        help="Ask for the passphrase its backups use.",
    )
    _server_settings(edit)

    remove = _verb(verbs, "remove", "Remove a server.", "servers:remove", location)
    remove.add_argument("server", help="The server's name or id.")
    _yes(remove)

    check = _verb(
        verbs,
        "check",
        "Check that servers are reachable and ready.",
        "servers:check",
        location,
    )
    check.add_argument("servers", nargs="*", metavar="SERVER")
    check.add_argument("--all", action="store_true", help="Check every server.")

    discover = _verb(
        verbs,
        "discover",
        "Find the project and the Python that has django-dbs.",
        "servers:discover",
        location,
    )
    discover.add_argument("server", help="The server's name or id.")
    discover.add_argument("--project", help="Look in this folder only.")
    discover.add_argument(
        "--save", action="store_true", help="Save what was found to the server."
    )

    browse = _verb(
        verbs, "browse", "List a folder on a server.", "servers:browse", location
    )
    browse.add_argument("server", help="The server's name or id.")
    browse.add_argument("path", nargs="?", help="The folder. Defaults to home.")

    public = _verb(
        verbs,
        "public-key",
        "Print a server's public key.",
        "servers:public_key",
        location,
    )
    public.add_argument("server", help="The server's name or id.")

    repin = _verb(
        verbs,
        "host-key",
        "Pin the host key a server offers now.",
        "servers:host_key",
        location,
    )
    repin.add_argument("server", help="The server's name or id.")
    repin.add_argument("--host-key", help="The host key to pin.")
    _yes(repin)

    passphrase = _verb(
        verbs,
        "passphrase",
        "Show the passphrase a server's backups use.",
        "servers:passphrase",
        location,
    )
    passphrase.add_argument("server", help="The server's name or id.")

    capture = _verb(
        verbs,
        "capture-passphrase",
        "Read the backup passphrase from the server itself.",
        "servers:capture_passphrase",
        location,
    )
    capture.add_argument("server", help="The server's name or id.")

    profiles = _verb(
        verbs,
        "import-profiles",
        "Add the servers of a dbs-client config file.",
        "servers:import_profiles",
        location,
    )
    profiles.add_argument(
        "file",
        nargs="?",
        help="The dbs-client.toml. Defaults to where dbs-client looks.",
    )
    _yes(profiles)


def backups(commands, location: Location) -> None:
    verbs = _area(commands, "backup", "Take, verify, restore and keep backups.")

    found = _verb(verbs, "list", "List the backups.", "backups:list_backups", location)
    found.add_argument("--server", help="Only this server's backups.")

    take = _verb(
        verbs,
        "take",
        "Take a backup of one, several or every server.",
        "backups:take",
        location,
    )
    take.add_argument("servers", nargs="*", metavar="SERVER")
    take.add_argument("--all", action="store_true", help="Back up every server.")

    verify = _verb(
        verbs, "verify", "Verify a backup end to end.", "backups:verify", location
    )
    verify.add_argument("backup", help="The backup's id.")

    restore = _verb(
        verbs,
        "restore",
        "Restore a backup. Rehearses unless --real is given.",
        "backups:restore",
        location,
    )
    restore.add_argument("backup", help="The backup's id.")
    restore.add_argument("--mode", choices=RESTORE_MODES, required=True)
    restore.add_argument("--to", help="Restore onto this server instead.")
    restore.add_argument(
        "--real", action="store_true", help="Restore for real, not a rehearsal."
    )
    restore.add_argument(
        "--confirm-name", help="The target server's name, instead of typing it."
    )

    download = _verb(
        verbs,
        "download",
        "Save a backup to this computer.",
        "backups:download",
        location,
    )
    download.add_argument("backup", help="The backup's id.")
    download.add_argument("-o", "--output", help="Where to save it.")

    upload = _verb(
        verbs, "upload", "Keep a file from this computer.", "backups:upload", location
    )
    upload.add_argument("server", help="The server it belongs to.")
    upload.add_argument("file", help="The file to keep.")

    delete = _verb(verbs, "delete", "Delete a backup.", "backups:delete", location)
    delete.add_argument("backup", help="The backup's id.")

    undo = _verb(
        verbs,
        "undo-delete",
        "Bring back a deleted backup.",
        "backups:undo_delete",
        location,
    )
    undo.add_argument("backup", help="The backup's id.")


def _plan_fields(parser) -> None:
    parser.add_argument(
        "--path",
        dest="paths",
        action="append",
        metavar="PATH",
        help="A folder to archive or collect from. Repeat for more.",
    )
    parser.add_argument("--pattern", help="Which file names to collect.")
    parser.add_argument(
        "--every",
        dest="interval_minutes",
        type=int,
        metavar="MINUTES",
        help="Run every this many minutes.",
    )
    parser.add_argument("--manual", action="store_true", help="Run only when asked.")
    parser.add_argument("--keep", type=int, help="How many to keep here.")
    parser.add_argument(
        "--keep-remote", type=int, help="How many to keep on the server."
    )


def plans(commands, location: Location) -> None:
    verbs = _area(commands, "plan", "Plan backups that run on their own.")

    found = _verb(verbs, "list", "List the plans.", "plans:list_plans", location)
    found.add_argument("--server", help="Only this server's plans.")

    show = _verb(verbs, "show", "Show one plan.", "plans:show", location)
    show.add_argument("plan", help="The plan's id.")

    add = _verb(verbs, "add", "Add a plan.", "plans:add", location)
    add.add_argument("server", help="The server's name or id.")
    add.add_argument("name", help="A name for the plan.")
    add.add_argument("--kind", choices=PLAN_KINDS, required=True)
    _plan_fields(add)
    add.add_argument("--disabled", action="store_true", help="Add it switched off.")

    edit = _verb(verbs, "edit", "Change a plan.", "plans:edit", location)
    edit.add_argument("plan", help="The plan's id.")
    edit.add_argument("--name", help="A new name.")
    _plan_fields(edit)
    switch = edit.add_mutually_exclusive_group()
    switch.add_argument("--enable", dest="enabled", action="store_true", default=None)
    switch.add_argument("--disable", dest="enabled", action="store_false")

    remove = _verb(verbs, "remove", "Remove a plan.", "plans:remove", location)
    remove.add_argument("plan", help="The plan's id.")

    run = _verb(verbs, "run", "Run a plan now.", "plans:run", location)
    run.add_argument("plan", help="The plan's id.")


def activity(commands, location: Location) -> None:
    verbs = _area(commands, "activity", "Read what the manager did.")

    found = _verb(
        verbs, "list", "List recent activity.", "activity:list_activity", location
    )
    found.add_argument("--server", help="Only this server's activity.")
    found.add_argument("--action", help="Only this action, for example backup.take.")
    found.add_argument("--status", choices=ACTIVITY_STATUSES)
    found.add_argument(
        "--limit", type=int, default=ACTIVITY_LIMIT, help="How many to show."
    )

    show = _verb(verbs, "show", "Show one entry.", "activity:show", location)
    show.add_argument("entry", help="The entry's number.")


def envfiles(commands, location: Location) -> None:
    verbs = _area(commands, "env", "Keep versions of a server's .env file.")

    found = _verb(
        verbs, "list", "List the kept versions.", "envfiles:list_versions", location
    )
    found.add_argument("server", help="The server's name or id.")

    pull = _verb(
        verbs, "pull", "Keep the .env file as it is now.", "envfiles:pull", location
    )
    pull.add_argument("server", help="The server's name or id.")

    compare = _verb(
        verbs, "compare", "Show which keys differ.", "envfiles:compare", location
    )
    compare.add_argument("version", help="The version's id.")
    compare.add_argument("other", help="The version to compare it with.")

    reveal = _verb(
        verbs, "reveal", "Print a kept version.", "envfiles:reveal", location
    )
    reveal.add_argument("version", help="The version's id.")

    push = _verb(
        verbs,
        "push",
        "Write a kept version back to its server.",
        "envfiles:push",
        location,
    )
    push.add_argument("version", help="The version's id.")


def files(commands, location: Location) -> None:
    verbs = _area(commands, "files", "Work with the files on a server.")

    found = _verb(verbs, "list", "List a folder.", "files:list_folder", location)
    found.add_argument("server", help="The server's name or id.")
    found.add_argument(
        "path", nargs="?", help="The folder. Defaults to the first root."
    )

    download = _verb(verbs, "download", "Save a file here.", "files:download", location)
    download.add_argument("server", help="The server's name or id.")
    download.add_argument("path", help="The file on the server.")
    download.add_argument("-o", "--output", help="Where to save it.")

    upload = _verb(
        verbs, "upload", "Put a file on the server.", "files:upload", location
    )
    upload.add_argument("server", help="The server's name or id.")
    upload.add_argument("folder", help="The folder on the server.")
    upload.add_argument("file", help="The file here.")

    folder = _verb(verbs, "mkdir", "Make a folder.", "files:mkdir", location)
    folder.add_argument("server", help="The server's name or id.")
    folder.add_argument("folder", help="The folder to make it in.")
    folder.add_argument("name", help="The new folder's name.")

    delete = _verb(
        verbs, "delete", "Delete a file or folder.", "files:delete", location
    )
    delete.add_argument("server", help="The server's name or id.")
    delete.add_argument("path", help="What to delete.")
    _yes(delete)


def redeploy(commands, location: Location) -> None:
    verbs = _area(commands, "redeploy", "Move a project from one server onto another.")
    start = _verb(
        verbs,
        "start",
        "Restore a server's backup onto another server. Rehearses unless --real.",
        "redeploy:start",
        location,
    )
    start.add_argument(
        "--from", dest="source", required=True, help="The source server."
    )
    start.add_argument("--to", dest="target", required=True, help="The target server.")
    start.add_argument("--backup", required=True, help="The source backup's id.")
    start.add_argument("--env", dest="env_version", help="A .env version to write.")
    start.add_argument(
        "--archive",
        dest="archives",
        action="append",
        default=[],
        metavar="ID",
        help="An archive to unpack. Repeat for more.",
    )
    start.add_argument("--migrate", action="store_true", help="Run migrate first.")
    start.add_argument("--flush", action="store_true", help="Empty the database first.")
    start.add_argument("--real", action="store_true", help="Redeploy for real.")
    start.add_argument(
        "--confirm-name", help="The target server's name, instead of typing it."
    )
