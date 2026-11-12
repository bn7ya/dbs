from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from dbs.manager.permissions import Capability

REFERENCE = "reference"
REFERENCES = "references"
IDENTIFIER = "identifier"
PARENT = "parent"
PARENTS = "parents"
FILES = "files"
FOLDERS = "folders"


@dataclass(frozen=True)
class Action:
    label: str
    path: tuple = ()
    fill: Mapping[str, str] = field(default_factory=dict)
    direct: bool = False
    danger: bool = False
    leaves: bool = False
    needs: str = ""
    listing: str = ""
    opens: str = ""
    detail: str = ""


@dataclass(frozen=True)
class Listing:
    title: str
    path: tuple
    fill: Mapping[str, str] = field(default_factory=dict)
    actions: tuple = ()
    adds: tuple = ()
    named: Any = "name"
    empty: str = ""
    straight: bool = False


SERVER = {"<server>": REFERENCE}
APPLICATION = {"<application>": REFERENCE}
BACKUP = {"<backup>": IDENTIFIER}
PLAN = {"<plan>": IDENTIFIER}
VERSION = {"<version>": IDENTIFIER}

LISTINGS = {
    "servers": Listing(
        "Servers",
        ("server", "list"),
        empty="No servers yet. Add a server, then the applications it runs.",
        actions=(
            Action("Details", ("server", "show"), SERVER, direct=True),
            Action("Applications", listing="server-applications"),
            Action(
                "Check the connection",
                ("server", "check"),
                {"<servers>": REFERENCES},
                direct=True,
                needs=Capability.SERVERS_CHECK,
            ),
            Action("Browse its folders", opens=FOLDERS),
            Action(
                "Add an application",
                ("app", "add"),
                {"--server": REFERENCE},
                needs=Capability.APPLICATIONS_MANAGE,
            ),
            Action("Activity", listing="server-activity"),
            Action("Edit", ("server", "edit"), SERVER, needs=Capability.SERVERS_MANAGE),
            Action("Public key", ("server", "public-key"), SERVER, direct=True),
            Action(
                "Pin its host key again",
                ("server", "host-key"),
                SERVER,
                needs=Capability.SERVERS_MANAGE,
            ),
            Action(
                "Join it into another server",
                ("server", "merge"),
                SERVER,
                needs=Capability.SERVERS_MANAGE,
            ),
            Action(
                "Move its applications to another server",
                ("server", "move"),
                SERVER,
                needs=Capability.RELOCATION_REHEARSE,
                detail="Rehearses by default.",
            ),
            Action(
                "Remove",
                ("server", "remove"),
                SERVER,
                direct=True,
                danger=True,
                leaves=True,
                needs=Capability.SERVERS_MANAGE,
            ),
        ),
        adds=(
            Action("Add a server", ("server", "add"), needs=Capability.SERVERS_MANAGE),
        ),
    ),
    "applications": Listing(
        "Applications",
        ("app", "list"),
        empty="No applications yet. Add one from a server's folder.",
        actions=(
            Action("Details", ("app", "show"), APPLICATION, direct=True),
            Action(
                "Back up now",
                ("backup", "take"),
                {"<applications>": REFERENCES},
                direct=True,
                needs=Capability.BACKUPS_TAKE,
            ),
            Action("Backups", listing="application-backups"),
            Action("Schedule", listing="application-plans"),
            Action("Files", opens=FILES),
            Action(".env file", listing="application-env"),
            Action(
                "Check",
                ("app", "check"),
                {"<applications>": REFERENCES},
                direct=True,
                needs=Capability.APPLICATIONS_CHECK,
            ),
            Action(
                "Deploy",
                ("app", "deploy"),
                APPLICATION,
                needs=Capability.REDEPLOY_REHEARSE,
                detail="Rehearses by default.",
            ),
            Action(
                "Deploy steps",
                ("app", "deploy-steps"),
                APPLICATION,
                needs=Capability.APPLICATIONS_MANAGE,
            ),
            Action(
                "Move it onto another application",
                ("redeploy", "start"),
                {"--from": REFERENCE},
                needs=Capability.REDEPLOY_REHEARSE,
                detail="Rehearses by default.",
            ),
            Action("Activity", listing="application-activity"),
            Action(
                "Edit",
                ("app", "edit"),
                APPLICATION,
                needs=Capability.APPLICATIONS_MANAGE,
            ),
            Action(
                "Show the backup passphrase",
                ("app", "passphrase"),
                APPLICATION,
                direct=True,
                needs=Capability.APPLICATIONS_PASSPHRASE,
            ),
            Action(
                "Read the backup passphrase from the server",
                ("app", "capture-passphrase"),
                APPLICATION,
                direct=True,
                needs=Capability.APPLICATIONS_MANAGE,
            ),
            Action(
                "Remove",
                ("app", "remove"),
                APPLICATION,
                direct=True,
                danger=True,
                leaves=True,
                needs=Capability.APPLICATIONS_MANAGE,
            ),
        ),
        adds=(
            Action(
                "Add an application",
                ("app", "add"),
                needs=Capability.APPLICATIONS_MANAGE,
            ),
            Action(
                "Find applications on a server",
                ("app", "discover"),
                needs=Capability.APPLICATIONS_MANAGE,
            ),
        ),
    ),
    "backups": Listing(
        "Backups",
        ("backup", "list"),
        empty="No backups yet. Back an application up, or wait for its plan.",
        actions=(
            Action(
                "Verify",
                ("backup", "verify"),
                BACKUP,
                direct=True,
                needs=Capability.BACKUPS_VERIFY,
            ),
            Action(
                "Restore",
                ("backup", "restore"),
                BACKUP,
                needs=Capability.BACKUPS_REHEARSE,
                detail="Rehearses by default.",
            ),
            Action(
                "Download",
                ("backup", "download"),
                BACKUP,
                needs=Capability.BACKUPS_DOWNLOAD,
            ),
            Action(
                "Delete",
                ("backup", "delete"),
                BACKUP,
                direct=True,
                danger=True,
                leaves=True,
                needs=Capability.BACKUPS_DELETE,
            ),
        ),
        adds=(
            Action(
                "Back up applications",
                ("backup", "take"),
                needs=Capability.BACKUPS_TAKE,
            ),
            Action(
                "Upload a backup", ("backup", "upload"), needs=Capability.BACKUPS_UPLOAD
            ),
            Action(
                "Put back a deleted backup",
                ("backup", "undo-delete"),
                needs=Capability.BACKUPS_DELETE,
            ),
        ),
    ),
    "activity": Listing(
        "Activity",
        ("activity", "list"),
        named="action",
        empty="Nothing has happened yet.",
        straight=True,
        actions=(
            Action(
                "Details", ("activity", "show"), {"<entry>": IDENTIFIER}, direct=True
            ),
        ),
    ),
}

LISTINGS["server-applications"] = Listing(
    "Applications",
    ("app", "list"),
    {"--server": PARENT},
    actions=LISTINGS["applications"].actions,
    adds=(
        Action(
            "Add an application",
            ("app", "add"),
            {"--server": PARENT},
            needs=Capability.APPLICATIONS_MANAGE,
        ),
    ),
    empty="This server runs no application yet.",
)
LISTINGS["server-activity"] = Listing(
    "Activity",
    ("activity", "list"),
    {"--server": PARENT},
    actions=LISTINGS["activity"].actions,
    named="action",
    empty="Nothing has happened on this server yet.",
    straight=True,
)
LISTINGS["application-activity"] = Listing(
    "Activity",
    ("activity", "list"),
    {"--app": PARENT},
    actions=LISTINGS["activity"].actions,
    named="action",
    empty="Nothing has happened to this application yet.",
    straight=True,
)
LISTINGS["application-backups"] = Listing(
    "Backups",
    ("backup", "list"),
    {"--app": PARENT},
    actions=LISTINGS["backups"].actions,
    adds=(
        Action(
            "Back up now",
            ("backup", "take"),
            {"<applications>": PARENTS},
            direct=True,
            needs=Capability.BACKUPS_TAKE,
        ),
        Action(
            "Upload a backup",
            ("backup", "upload"),
            {"<application>": PARENT},
            needs=Capability.BACKUPS_UPLOAD,
        ),
    ),
    empty="No backups of this application yet.",
)
LISTINGS["application-plans"] = Listing(
    "Schedule",
    ("plan", "list"),
    {"--app": PARENT},
    actions=(
        Action("Details", ("plan", "show"), PLAN, direct=True),
        Action(
            "Run it now", ("plan", "run"), PLAN, direct=True, needs=Capability.PLANS_RUN
        ),
        Action(
            "Pause", ("plan", "pause"), PLAN, direct=True, needs=Capability.PLANS_MANAGE
        ),
        Action(
            "Resume",
            ("plan", "resume"),
            PLAN,
            direct=True,
            needs=Capability.PLANS_MANAGE,
        ),
        Action(
            "Change its next run",
            ("plan", "reschedule"),
            PLAN,
            needs=Capability.PLANS_MANAGE,
        ),
        Action("Edit", ("plan", "edit"), PLAN, needs=Capability.PLANS_MANAGE),
        Action(
            "Remove",
            ("plan", "remove"),
            PLAN,
            direct=True,
            danger=True,
            leaves=True,
            needs=Capability.PLANS_MANAGE,
        ),
    ),
    adds=(
        Action(
            "Add a plan",
            ("plan", "add"),
            {"<application>": PARENT},
            needs=Capability.PLANS_MANAGE,
        ),
    ),
    empty="No plan yet. Add one so this application is backed up on a schedule.",
)
LISTINGS["application-env"] = Listing(
    ".env file",
    ("env", "list"),
    {"<application>": PARENT},
    named="created_at",
    actions=(
        Action(
            "Show it",
            ("env", "reveal"),
            VERSION,
            direct=True,
            needs=Capability.ENV_REVEAL,
        ),
        Action(
            "Compare with another version",
            ("env", "compare"),
            VERSION,
        ),
        Action(
            "Write it to the server",
            ("env", "push"),
            VERSION,
            direct=True,
            danger=True,
            needs=Capability.ENV_PUSH,
        ),
    ),
    adds=(
        Action(
            "Keep the file as it is now",
            ("env", "pull"),
            {"<application>": PARENT},
            direct=True,
            needs=Capability.ENV_PULL,
        ),
    ),
    empty="No version kept yet. Keep the file as it is now to start.",
)
