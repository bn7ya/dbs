from __future__ import annotations

from dataclasses import dataclass

from .commands import SWITCH, Argument, Verb

TEXT = "text"
SERVER = "server"
SERVERS = "servers"
APPLICATION = "application"
APPLICATIONS = "applications"
BACKUP = "backup"
PLAN = "plan"
VERSION = "version"
ACTIVITY = "activity"
ACCOUNT = "account"
LOCAL_FILE = "local file"
LOCAL_TARGET = "local target"
SERVER_FOLDER = "server folder"
APPLICATION_PATH = "application path"
APPLICATION_FOLDER = "application folder"

HIDDEN = frozenset(
    {
        "--json",
        "--as",
        "--password-stdin",
        "--ssh-password-stdin",
        "--sudo-password-stdin",
        "--passphrase-stdin",
        "--data-dir",
        "--database-url",
        "--yes",
        "--confirm-name",
    }
)
NAMED_ONLY = frozenset({("import",), ("mcp",), ("menu",)})
NAMED_BECAUSE = {
    (
        "import",
    ): "An import replaces the data folder this menu is working in. Close the "
    "menu and stop the manager, then type the command.",
    ("mcp",): "This is the server Claude starts by itself. Add it to Claude with:\n"
    "claude mcp add dbs -- django_dbs mcp",
    ("menu",): "You are in the menu.",
}


@dataclass(frozen=True)
class Meaning:
    kind: str
    of: str = ""


@dataclass(frozen=True)
class Secret:
    label: str
    prompt: str


COMMON = {
    "<server>": Meaning(SERVER),
    "<servers>": Meaning(SERVERS),
    "<application>": Meaning(APPLICATION),
    "<applications>": Meaning(APPLICATIONS),
    "<backup>": Meaning(BACKUP),
    "<plan>": Meaning(PLAN),
    "<version>": Meaning(VERSION),
    "<other>": Meaning(VERSION),
    "<entry>": Meaning(ACTIVITY),
    "<move>": Meaning(ACTIVITY),
    "<confirmation>": Meaning(TEXT),
    "--server": Meaning(SERVER),
    "--search": Meaning(TEXT),
    "--name": Meaning(TEXT),
    "--host": Meaning(TEXT),
    "--port": Meaning(TEXT),
    "--user": Meaning(TEXT),
    "--key-file": Meaning(LOCAL_FILE),
    "--host-key": Meaning(TEXT),
    "--deployment": Meaning(TEXT),
    "--compose-project": Meaning(TEXT),
    "--compose-service": Meaning(TEXT),
    "--compose-file": Meaning(TEXT),
    "--container": Meaning(TEXT),
    "--project-dir": Meaning(TEXT),
    "--workdir": Meaning(TEXT),
    "--python": Meaning(TEXT),
    "--manage": Meaning(TEXT),
    "--settings": Meaning(TEXT),
    "--backup-dir": Meaning(TEXT),
    "--env-path": Meaning(TEXT),
    "--file-root": Meaning(TEXT),
    "--path": Meaning(TEXT),
    "--pattern": Meaning(TEXT),
    "--every": Meaning(TEXT),
    "--first-run": Meaning(TEXT),
    "--time-zone": Meaning(TEXT),
    "--output": Meaning(LOCAL_TARGET),
}
SPECIFIC = {
    ("run",): {"--trusted-proxy": Meaning(TEXT)},
    ("createuser",): {"<name>": Meaning(TEXT)},
    ("password",): {"<name>": Meaning(ACCOUNT)},
    ("account", "role"): {"<name>": Meaning(ACCOUNT)},
    ("account", "disable"): {"<name>": Meaning(ACCOUNT)},
    ("account", "enable"): {"<name>": Meaning(ACCOUNT)},
    ("account", "reset-2fa"): {"<name>": Meaning(ACCOUNT)},
    ("export",): {"<file>": Meaning(LOCAL_TARGET)},
    ("import",): {"<file>": Meaning(LOCAL_FILE)},
    ("server", "add"): {"<name>": Meaning(TEXT)},
    ("server", "move"): {
        "--to": Meaning(SERVER),
        "--app": Meaning(TEXT),
        "--skip-volume": Meaning(TEXT),
        "--resume": Meaning(ACTIVITY),
    },
    ("server", "merge"): {"--into": Meaning(SERVER)},
    ("server", "browse"): {"<path>": Meaning(SERVER_FOLDER, "<server>")},
    ("app", "discover"): {"--folder": Meaning(SERVER_FOLDER, "<server>")},
    ("app", "add"): {
        "<name>": Meaning(TEXT),
        "--folder": Meaning(SERVER_FOLDER, "--server"),
        "--candidate": Meaning(TEXT),
    },
    ("app", "deploy-steps"): {"--set": Meaning(LOCAL_FILE)},
    ("backup", "list"): {"--app": Meaning(APPLICATION)},
    ("backup", "restore"): {"--to": Meaning(APPLICATION)},
    ("backup", "upload"): {"<file>": Meaning(LOCAL_FILE)},
    ("plan", "list"): {"--app": Meaning(APPLICATION)},
    ("plan", "add"): {"<name>": Meaning(TEXT)},
    ("plan", "reschedule"): {"--at": Meaning(TEXT)},
    ("activity", "list"): {
        "--app": Meaning(APPLICATION),
        "--action": Meaning(TEXT),
        "--limit": Meaning(TEXT),
    },
    ("files", "list"): {"<path>": Meaning(APPLICATION_FOLDER, "<application>")},
    ("files", "download"): {"<path>": Meaning(APPLICATION_PATH, "<application>")},
    ("files", "upload"): {
        "<folder>": Meaning(APPLICATION_FOLDER, "<application>"),
        "<file>": Meaning(LOCAL_FILE),
    },
    ("files", "mkdir"): {
        "<folder>": Meaning(APPLICATION_FOLDER, "<application>"),
        "<name>": Meaning(TEXT),
    },
    ("files", "delete"): {"<path>": Meaning(APPLICATION_PATH, "<application>")},
    ("redeploy", "start"): {
        "--from": Meaning(APPLICATION),
        "--to": Meaning(APPLICATION),
        "--backup": Meaning(BACKUP),
        "--env": Meaning(VERSION, "--from"),
    },
}
ONE_OF = {
    ("server", "add"): (
        ("--key-file", "--ssh-password", "--generate-key"),
        "Choose how to sign in: a key file, an SSH password or a generated key.",
    ),
    ("plan", "add"): (
        ("--every", "--manual"),
        "Say how often it runs, or that it only runs by hand.",
    ),
    ("backup", "take"): (
        ("<applications>", "--all"),
        "Choose the applications, or all of them.",
    ),
    ("app", "check"): (
        ("<applications>", "--all"),
        "Choose the applications, or all of them.",
    ),
    ("server", "check"): (
        ("<servers>", "--all"),
        "Choose the servers, or all of them.",
    ),
}
ASKS_FIRST = {
    ("plan", "remove"): "Remove this plan? The backups it took stay.",
    ("backup", "delete"): "Delete this backup? It can be put back with Undo delete "
    "until it expires.",
    ("env", "push"): "Write this version over the .env file on the server? The file "
    "there now is kept as a version first.",
}
SHOWS_SECRET = frozenset({("app", "passphrase"), ("env", "reveal")})
LABELS = {
    "--generate-key": "Generate a new key",
    "--python": "Python",
    "--manage": "manage.py",
    "--settings": "Settings module",
    "--env-path": ".env path",
    "--env-location": ".env location",
    "--real": "For real, not a rehearsal",
    "--every": "Every (minutes)",
    "--set": "Steps file",
    "--app": "Application",
    "--at": "Next run",
    "--no-sudo-password": "sudo asks no password there",
    "--source-sudo-password": "Ask the sudo password of the old server",
}


SECRETS = {
    "--ssh-password": Secret("SSH password", "SSH password"),
    "--key-passphrase": Secret("Passphrase of the key file", "Key passphrase"),
    "--backup-passphrase": Secret("Backup passphrase", "Backup passphrase"),
}
SECRET_NOTE = (
    "Typed here, it is used for this one command and not kept. The command line "
    "below only says that one is given."
)


def label(argument: Argument) -> str:
    if argument.key in SECRETS:
        return SECRETS[argument.key].label
    return LABELS.get(argument.key, argument.label)


def hidden(argument: Argument) -> bool:
    return argument.key in HIDDEN


def offered(verb: Verb) -> list[Argument]:
    return [argument for argument in verb.arguments if not hidden(argument)]


def meaning(verb: Verb, argument: Argument) -> Meaning:
    if argument.kind == SWITCH or argument.choices:
        return Meaning(TEXT)
    specific = SPECIFIC.get(verb.path, {})
    return specific.get(argument.key) or COMMON.get(argument.key) or Meaning(TEXT)
