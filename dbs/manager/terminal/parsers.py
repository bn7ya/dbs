from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass

from dbs.manager.applications.deployment import QUESTIONS

RESTORE_MODES = ("merge", "replace")
PLAN_KINDS = ("dbs", "archive", "collect")
ACTIVITY_STATUSES = ("queued", "running", "succeeded", "failed")
ACTIVITY_LIMIT = 20
KEEP_CHOICES = range(1, 6)
KEEP_REMOTE_CHOICES = range(0, 6)

LOCAL_HANDLERS = frozenset(
    {
        "terminal.backups:download",
        "terminal.backups:upload",
        "terminal.files:download",
        "terminal.files:upload",
        "terminal.servers:add",
        "terminal.servers:edit",
        "terminal.applications:passphrase",
        "terminal.envfiles:reveal",
    }
)


def _nothing(parser: argparse.ArgumentParser) -> None:
    return None


@dataclass(frozen=True)
class Surface:
    extend: Callable[[argparse.ArgumentParser], None] = _nothing
    console: bool = False

    def offers(self, handler: str) -> bool:
        return not (self.console and handler in LOCAL_HANDLERS)


CONSOLE = Surface(console=True)


def register(commands, surface: Surface) -> None:
    for build in (
        servers,
        applications,
        backups,
        plans,
        activity,
        envfiles,
        files,
        redeploy,
        mcp,
    ):
        build(commands, surface)


def mcp(commands, surface: Surface) -> None:
    if surface.console:
        return
    help_text = "Let Claude drive the manager: an MCP server on stdin and stdout."
    serve = commands.add_parser("mcp", help=help_text, description=help_text)
    serve.set_defaults(handler="mcp.server:serve")
    surface.extend(serve)
    serve.add_argument(
        "--as",
        dest="account",
        metavar="NAME",
        help="The account Claude acts as. Defaults to the only account.",
    )


def _area(commands, name: str, help_text: str):
    area = commands.add_parser(name, help=help_text, description=help_text)
    return area.add_subparsers(dest="verb", metavar="VERB", required=True)


def _verb(verbs, name: str, help_text: str, handler: str, surface: Surface):
    if not surface.offers(handler):
        return argparse.ArgumentParser(add_help=False)
    verb = verbs.add_parser(name, help=help_text, description=help_text)
    verb.set_defaults(handler=handler)
    surface.extend(verb)
    verb.add_argument(
        "--json", action="store_true", help="Print what the web API would return."
    )
    if surface.console:
        return verb
    verb.add_argument(
        "--as",
        dest="account",
        metavar="NAME",
        help="The account to act as. Defaults to the only account.",
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


def _deployment(parser) -> None:
    parser.add_argument(
        "--deployment",
        dest="deployment_answers",
        action="append",
        metavar="KEY=VALUE",
        help="How the application is deployed, one answer each: "
        + "; ".join(f"{key}={'|'.join(values)}" for key, values in QUESTIONS.items())
        + ". An empty value means not sure.",
    )


def _application_settings(parser) -> None:
    _deployment(parser)
    parser.add_argument(
        "--kind",
        choices=("host", "compose", "container"),
        help="Where the application runs: on the server itself, in a Compose "
        "service, or in a container.",
    )
    parser.add_argument(
        "--engine",
        choices=("docker", "podman"),
        help="The container engine for --kind compose or container.",
    )
    parser.add_argument(
        "--compose-project", help="The Compose project name, when it is not the folder's."
    )
    parser.add_argument(
        "--compose-service",
        help="The Compose service that runs the application, such as backend.",
    )
    parser.add_argument(
        "--compose-file",
        dest="compose_files",
        action="append",
        metavar="PATH",
        help="A compose file to pass with -f. Repeat for more, in order.",
    )
    parser.add_argument(
        "--container", dest="container_name", help="The container for --kind container."
    )
    parser.add_argument(
        "--project-dir",
        help="The folder on the server that holds manage.py or the compose file.",
    )
    parser.add_argument(
        "--workdir", help="The folder inside the container that holds manage.py."
    )
    parser.add_argument(
        "--python",
        dest="python_path",
        help="The Python to run; inside the container for a container application.",
    )
    parser.add_argument(
        "--manage",
        dest="manage_path",
        help="The manage.py to run; inside the container for a container application.",
    )
    parser.add_argument(
        "--settings", dest="settings_module", help="DJANGO_SETTINGS_MODULE to use."
    )
    parser.add_argument(
        "--backup-dir",
        dest="remote_backup_dir",
        help="Where the application writes its backups.",
    )
    parser.add_argument("--env-path", help="The .env file to keep versions of.")
    parser.add_argument(
        "--env-location",
        choices=("host", "container"),
        help="Whether --env-path is on the server or inside the container.",
    )
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


def servers(commands, surface: Surface) -> None:
    verbs = _area(commands, "server", "Add, change, check and remove servers.")

    found = _verb(
        verbs, "list", "List the servers.", "terminal.servers:list_servers", surface
    )
    found.add_argument("--search", help="Only servers whose name or host has this.")

    show = _verb(verbs, "show", "Show one server.", "terminal.servers:show", surface)
    show.add_argument("server", help="The server's name or id.")

    add = _verb(
        verbs,
        "add",
        "Add a server: confirm its host key, sign in and check it.",
        "terminal.servers:add",
        surface,
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
    _yes(add)

    edit = _verb(
        verbs, "edit", "Change how to reach a server.", "terminal.servers:edit", surface
    )
    edit.add_argument("server", help="The server's name or id.")
    edit.add_argument("--name", help="A new name.")
    edit.add_argument("--host", help="A new address.")
    edit.add_argument("--port", type=int, help="A new SSH port.")
    edit.add_argument("--user", dest="username", help="A new SSH account.")
    _ssh_auth(edit)

    remove = _verb(
        verbs,
        "remove",
        "Remove a server that runs no application. It asks for its name and your "
        "password.",
        "terminal.servers:remove",
        surface,
    )
    remove.add_argument("server", help="The server's name or id.")
    _yes(remove)

    check = _verb(
        verbs,
        "check",
        "Check that servers answer and which container engines they have.",
        "terminal.servers:check",
        surface,
    )
    check.add_argument("servers", nargs="*", metavar="SERVER")
    check.add_argument("--all", action="store_true", help="Check every server.")

    _server_move(verbs, surface)

    merge = _verb(
        verbs,
        "merge",
        "Join a server into another that is the same machine: its applications move "
        "and it is removed. It asks for your password.",
        "terminal.servers:merge",
        surface,
    )
    merge.add_argument("server", help="The server to join into the other.")
    merge.add_argument("--into", required=True, help="The server that stays.")

    browse = _verb(
        verbs,
        "browse",
        "List a folder on a server.",
        "terminal.servers:browse",
        surface,
    )
    browse.add_argument("server", help="The server's name or id.")
    browse.add_argument("path", nargs="?", help="The folder. Defaults to home.")

    public = _verb(
        verbs,
        "public-key",
        "Print a server's public key.",
        "terminal.servers:public_key",
        surface,
    )
    public.add_argument("server", help="The server's name or id.")

    repin = _verb(
        verbs,
        "host-key",
        "Pin the host key a server offers now.",
        "terminal.servers:host_key",
        surface,
    )
    repin.add_argument("server", help="The server's name or id.")
    repin.add_argument("--host-key", help="The host key to pin.")
    _yes(repin)

    confirm_key = _verb(
        verbs,
        "confirm-host-key",
        "Confirm or reject a host key Claude read with fingerprint_host. It shows the "
        "fingerprint and asks; only a confirmed key can be pinned by Claude.",
        "terminal.servers:confirm_host_key",
        surface,
    )
    confirm_key.add_argument(
        "confirmation", help="The confirmation id Claude was given."
    )


def applications(commands, surface: Surface) -> None:
    verbs = _area(
        commands,
        "app",
        "Find, add, change, check and remove the Django applications on servers.",
    )

    found = _verb(
        verbs,
        "list",
        "List the applications.",
        "terminal.applications:list_applications",
        surface,
    )
    found.add_argument("--server", help="Only the applications on this server.")
    found.add_argument("--search", help="Only applications whose name has this.")

    show = _verb(
        verbs, "show", "Show one application.", "terminal.applications:show", surface
    )
    show.add_argument("application", help="The application's name or id.")

    discover = _verb(
        verbs,
        "discover",
        "Look in a folder on a server for the application: on the server itself, "
        "in Compose services or in containers, with Docker or Podman.",
        "terminal.applications:discover",
        surface,
    )
    discover.add_argument("server", help="The server's name or id.")
    discover.add_argument(
        "--folder",
        default="",
        help="The application's folder on the server. Without it, folders that "
        "look like projects are suggested.",
    )
    _deployment(discover)

    add = _verb(
        verbs,
        "add",
        "Add the application found in a folder, then check it.",
        "terminal.applications:add",
        surface,
    )
    add.add_argument("name", help="A name for this application.")
    add.add_argument("--server", required=True, help="The server it runs on.")
    add.add_argument(
        "--folder", required=True, help="The application's folder on the server."
    )
    add.add_argument(
        "--candidate",
        type=int,
        default=1,
        metavar="N",
        help="Which of the places found to add, from app discover. Defaults to the "
        "first.",
    )
    add.add_argument(
        "--backup-passphrase",
        action="store_true",
        help="Ask for the passphrase its backups use. Defaults to a new random one.",
    )
    _application_settings(add)

    edit = _verb(
        verbs,
        "edit",
        "Change an application's settings.",
        "terminal.applications:edit",
        surface,
    )
    edit.add_argument("application", help="The application's name or id.")
    edit.add_argument("--name", help="A new name.")
    _application_settings(edit)

    remove = _verb(
        verbs,
        "remove",
        "Remove an application. It asks for its name and your password.",
        "terminal.applications:remove",
        surface,
    )
    remove.add_argument("application", help="The application's name or id.")
    _yes(remove)

    check = _verb(
        verbs,
        "check",
        "Check that applications are ready to back up.",
        "terminal.applications:check",
        surface,
    )
    check.add_argument("applications", nargs="*", metavar="APPLICATION")
    check.add_argument("--all", action="store_true", help="Check every application.")

    passphrase = _verb(
        verbs,
        "passphrase",
        "Show the passphrase an application's backups use. Never change it: older "
        "backups would no longer open.",
        "terminal.applications:passphrase",
        surface,
    )
    passphrase.add_argument("application", help="The application's name or id.")

    capture = _verb(
        verbs,
        "capture-passphrase",
        "Read the backup passphrase from the application itself. Do it only while "
        "adding it, before its first backup: an application's backup passphrase "
        "must never change, because older backups would no longer open.",
        "terminal.applications:capture_passphrase",
        surface,
    )
    capture.add_argument("application", help="The application's name or id.")

    deploy = _verb(
        verbs,
        "deploy",
        "Deploy an application in place: check it, back it up, record its .env, run "
        "its deploy steps and check it again. Rehearses unless --real.",
        "terminal.redeploy:deploy",
        surface,
    )
    deploy.add_argument("application", help="The application's name or id.")
    deploy.add_argument("--real", action="store_true", help="Deploy for real.")
    deploy.add_argument(
        "--confirm-name", help="The application's name, instead of typing it."
    )

    steps = _verb(
        verbs,
        "deploy-steps",
        "Show an application's deploy steps, or set them from a JSON file.",
        "terminal.redeploy:deploy_steps",
        surface,
    )
    steps.add_argument("application", help="The application's name or id.")
    if surface.console:
        return
    steps.add_argument(
        "--set",
        dest="steps_file",
        metavar="FILE",
        help='A JSON list such as [{"kind": "git_pull"}, {"kind": "migrate"}]. '
        "Setting them asks for your password.",
    )


def backups(commands, surface: Surface) -> None:
    verbs = _area(commands, "backup", "Take, verify, restore and keep backups.")

    found = _verb(
        verbs, "list", "List the backups.", "terminal.backups:list_backups", surface
    )
    found.add_argument("--app", dest="application", help="Only this application's backups.")

    take = _verb(
        verbs,
        "take",
        "Take a backup of one, several or every application.",
        "terminal.backups:take",
        surface,
    )
    take.add_argument("applications", nargs="*", metavar="APPLICATION")
    take.add_argument("--all", action="store_true", help="Back up every application.")

    verify = _verb(
        verbs,
        "verify",
        "Verify a backup end to end.",
        "terminal.backups:verify",
        surface,
    )
    verify.add_argument("backup", help="The backup's id.")

    restore = _verb(
        verbs,
        "restore",
        "Restore a backup. Rehearses unless --real is given.",
        "terminal.backups:restore",
        surface,
    )
    restore.add_argument("backup", help="The backup's id.")
    restore.add_argument("--mode", choices=RESTORE_MODES, required=True)
    restore.add_argument("--to", help="Restore into this application instead.")
    restore.add_argument(
        "--real", action="store_true", help="Restore for real, not a rehearsal."
    )
    restore.add_argument(
        "--confirm-name", help="The target application's name, instead of typing it."
    )

    download = _verb(
        verbs,
        "download",
        "Save a backup to this computer, readable by you alone. A backup the "
        "manager keeps encrypted asks for your password.",
        "terminal.backups:download",
        surface,
    )
    download.add_argument("backup", help="The backup's id.")
    download.add_argument("-o", "--output", help="Where to save it.")

    upload = _verb(
        verbs,
        "upload",
        "Keep a file from this computer.",
        "terminal.backups:upload",
        surface,
    )
    upload.add_argument("application", help="The application it belongs to.")
    upload.add_argument("file", help="The file to keep.")

    delete = _verb(
        verbs,
        "delete",
        "Delete a backup. It asks for your password.",
        "terminal.backups:delete",
        surface,
    )
    delete.add_argument("backup", help="The backup's id.")

    undo = _verb(
        verbs,
        "undo-delete",
        "Bring back a deleted backup.",
        "terminal.backups:undo_delete",
        surface,
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
    parser.add_argument(
        "--keep",
        type=int,
        choices=KEEP_CHOICES,
        metavar="N",
        help="How many to keep here, 1 to 5. Keeping fewer asks for your password.",
    )
    parser.add_argument(
        "--keep-remote",
        type=int,
        choices=KEEP_REMOTE_CHOICES,
        metavar="N",
        help="How many to leave on the server, 0 to 5. Keeping fewer asks for your "
        "password.",
    )
    parser.add_argument(
        "--first-run",
        dest="anchor_at",
        metavar="WHEN",
        help="When the first run happens, as 2026-11-02T03:00+01:00. Later runs keep "
        "its beat.",
    )
    parser.add_argument(
        "--time-zone",
        metavar="ZONE",
        help="The time zone whose clock a daily plan keeps, as Europe/Berlin.",
    )


def plans(commands, surface: Surface) -> None:
    verbs = _area(commands, "plan", "Plan backups that run on their own.")

    found = _verb(
        verbs, "list", "List the plans.", "terminal.plans:list_plans", surface
    )
    found.add_argument("--app", dest="application", help="Only this application's plans.")

    show = _verb(verbs, "show", "Show one plan.", "terminal.plans:show", surface)
    show.add_argument("plan", help="The plan's id.")

    add = _verb(verbs, "add", "Add a plan.", "terminal.plans:add", surface)
    add.add_argument("application", help="The application's name or id.")
    add.add_argument("name", help="A name for the plan.")
    add.add_argument("--kind", choices=PLAN_KINDS, required=True)
    _plan_fields(add)
    add.add_argument("--disabled", action="store_true", help="Add it switched off.")

    edit = _verb(verbs, "edit", "Change a plan.", "terminal.plans:edit", surface)
    edit.add_argument("plan", help="The plan's id.")
    edit.add_argument("--name", help="A new name.")
    _plan_fields(edit)
    switch = edit.add_mutually_exclusive_group()
    switch.add_argument("--enable", dest="enabled", action="store_true", default=None)
    switch.add_argument("--disable", dest="enabled", action="store_false")

    remove = _verb(verbs, "remove", "Remove a plan.", "terminal.plans:remove", surface)
    remove.add_argument("plan", help="The plan's id.")

    run = _verb(verbs, "run", "Run a plan now.", "terminal.plans:run", surface)
    run.add_argument("plan", help="The plan's id.")

    reschedule = _verb(
        verbs,
        "reschedule",
        "Move a plan's next run; later runs follow from it.",
        "terminal.plans:reschedule",
        surface,
    )
    reschedule.add_argument("plan", help="The plan's id.")
    reschedule.add_argument(
        "--at",
        dest="next_run_at",
        required=True,
        metavar="WHEN",
        help="The new next run, as 2026-11-02T03:00+01:00.",
    )

    pause = _verb(
        verbs, "pause", "Stop a plan's runs until resumed.", "terminal.plans:pause", surface
    )
    pause.add_argument("plan", help="The plan's id.")

    resume = _verb(
        verbs,
        "resume",
        "Start a paused plan again at its next beat.",
        "terminal.plans:resume",
        surface,
    )
    resume.add_argument("plan", help="The plan's id.")


def activity(commands, surface: Surface) -> None:
    verbs = _area(commands, "activity", "Read what the manager did.")

    found = _verb(
        verbs,
        "list",
        "List recent activity.",
        "terminal.activity:list_activity",
        surface,
    )
    found.add_argument(
        "--server", help="Only this server's activity and its applications'."
    )
    found.add_argument("--app", dest="application", help="Only this application's activity.")
    found.add_argument("--action", help="Only this action, for example backup.take.")
    found.add_argument("--status", choices=ACTIVITY_STATUSES)
    found.add_argument(
        "--limit", type=int, default=ACTIVITY_LIMIT, help="How many to show."
    )

    show = _verb(verbs, "show", "Show one entry.", "terminal.activity:show", surface)
    show.add_argument("entry", help="The entry's number.")


def envfiles(commands, surface: Surface) -> None:
    verbs = _area(commands, "env", "Keep versions of an application's .env file.")

    found = _verb(
        verbs,
        "list",
        "List the kept versions.",
        "terminal.envfiles:list_versions",
        surface,
    )
    found.add_argument("application", help="The application's name or id.")

    pull = _verb(
        verbs,
        "pull",
        "Keep the .env file as it is now.",
        "terminal.envfiles:pull",
        surface,
    )
    pull.add_argument("application", help="The application's name or id.")

    compare = _verb(
        verbs,
        "compare",
        "Show which keys differ.",
        "terminal.envfiles:compare",
        surface,
    )
    compare.add_argument("version", help="The version's id.")
    compare.add_argument("other", help="The version to compare it with.")

    reveal = _verb(
        verbs, "reveal", "Print a kept version.", "terminal.envfiles:reveal", surface
    )
    reveal.add_argument("version", help="The version's id.")

    push = _verb(
        verbs,
        "push",
        "Write a kept version back to its application.",
        "terminal.envfiles:push",
        surface,
    )
    push.add_argument("version", help="The version's id.")


def files(commands, surface: Surface) -> None:
    verbs = _area(commands, "files", "Work with an application's files on its server.")

    found = _verb(
        verbs, "list", "List a folder.", "terminal.files:list_folder", surface
    )
    found.add_argument("application", help="The application's name or id.")
    found.add_argument(
        "path", nargs="?", help="The folder. Defaults to the first root."
    )

    download = _verb(
        verbs,
        "download",
        "Save a file here, readable by you alone. A .env file asks for your password.",
        "terminal.files:download",
        surface,
    )
    download.add_argument("application", help="The application's name or id.")
    download.add_argument("path", help="The file on the server.")
    download.add_argument("-o", "--output", help="Where to save it.")

    upload = _verb(
        verbs, "upload", "Put a file on the server.", "terminal.files:upload", surface
    )
    upload.add_argument("application", help="The application's name or id.")
    upload.add_argument("folder", help="The folder on the server.")
    upload.add_argument("file", help="The file here.")

    folder = _verb(verbs, "mkdir", "Make a folder.", "terminal.files:mkdir", surface)
    folder.add_argument("application", help="The application's name or id.")
    folder.add_argument("folder", help="The folder to make it in.")
    folder.add_argument("name", help="The new folder's name.")

    delete = _verb(
        verbs, "delete", "Delete a file or folder.", "terminal.files:delete", surface
    )
    delete.add_argument("application", help="The application's name or id.")
    delete.add_argument("path", help="What to delete.")
    _yes(delete)


def _server_move(verbs, surface: Surface) -> None:
    move = _verb(
        verbs,
        "move",
        "Move a server's applications onto another server, which may have nothing "
        "installed: plan it, install what is missing with sudo, carry each "
        "application's folder with its git, images, volumes, files and .env, start "
        "it, restore its data and check it. The old server is left as it is. "
        "Rehearses unless --real.",
        "terminal.relocation:move",
        surface,
    )
    move.add_argument("server", help="The server the applications run on now.")
    move.add_argument(
        "--to", dest="target", required=True, help="The server to move them to."
    )
    move.add_argument(
        "--app",
        dest="apps",
        action="append",
        metavar="NAME[=FOLDER]",
        help="An application to move, and the folder it goes to on the new server. "
        "Repeat for more; without it every application moves to the same folders.",
    )
    move.add_argument(
        "--name",
        dest="names",
        action="append",
        metavar="APP=NEW",
        help="The name an application takes on the new server; without it, its name and the new server's in brackets.",
    )
    move.add_argument(
        "--skip-volume",
        dest="skip_volumes",
        action="append",
        metavar="APP:VOLUME",
        help="A volume to leave behind.",
    )
    move.add_argument(
        "--no-plans",
        action="store_true",
        help="Do not copy the backup plans; they are copied paused otherwise.",
    )
    move.add_argument("--real", action="store_true", help="Move for real.")
    move.add_argument(
        "--confirm-name", help="The new server's name, instead of typing it."
    )
    move.add_argument(
        "--resume", metavar="JOB_ID", help="Resume a move that stopped, from where it did."
    )
    move.add_argument(
        "--no-sudo-password",
        action="store_true",
        help="The SSH user is root, or runs sudo without a password.",
    )
    move.add_argument(
        "--source-sudo-password",
        action="store_true",
        help="Ask the sudo password on the old server too, to read what its SSH user "
        "cannot.",
    )
    if not surface.console:
        move.add_argument(
            "--sudo-password-stdin",
            action="store_true",
            help="Read the sudo password from stdin, on the line after the account "
            "password.",
        )


def redeploy(commands, surface: Surface) -> None:
    verbs = _area(
        commands, "redeploy", "Move an application onto another, on any server."
    )
    start = _verb(
        verbs,
        "start",
        "Move an application onto a new one with the same environment: back up the "
        "old one now, record the new one, push the .env, migrate, restore and "
        "check. Rehearses unless --real.",
        "terminal.redeploy:start",
        surface,
    )
    start.add_argument(
        "--from", dest="source", required=True, help="The old application."
    )
    start.add_argument(
        "--to", dest="target", required=True, help="The new application."
    )
    start.add_argument(
        "--backup",
        help="The old application's backup to restore when it cannot be reached. "
        "Defaults to its newest.",
    )
    start.add_argument("--env", dest="env_version", help="A .env version to push.")
    start.add_argument(
        "--flush", action="store_true", help="Replace the new application's data."
    )
    start.add_argument("--real", action="store_true", help="Move for real.")
    start.add_argument(
        "--confirm-name", help="The new application's name, instead of typing it."
    )

    revert = _verb(
        verbs,
        "revert",
        "Put an application back as it was before a move or a deploy that stopped: "
        "push a moved application's recorded .env back and restore the safety "
        "backup. Rehearses unless --real.",
        "terminal.redeploy:revert",
        surface,
    )
    revert.add_argument(
        "move", metavar="JOB_ID", help="The move's or deploy's activity number."
    )
    revert.add_argument("--real", action="store_true", help="Revert for real.")
    revert.add_argument(
        "--confirm-name", help="The new application's name, instead of typing it."
    )
