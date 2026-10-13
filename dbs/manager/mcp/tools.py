from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dbs.manager.activity.serializers import (
    ActivityFilterSerializer,
    ActivitySerializer,
)
from dbs.manager.activity.services import ActivityService
from dbs.manager.adapters import AdapterError, backups, jobs, references, servers
from dbs.manager.adapters.forms import validated
from dbs.manager.backups.serializers import (
    BackupFileSerializer,
    BackupPlanSerializer,
    PlanCreateSerializer,
    PlanUpdateSerializer,
    RestoreSerializer,
)
from dbs.manager.backups.services import BackupPlanService, BackupService
from dbs.manager.dashboard.serializers import DashboardSerializer
from dbs.manager.dashboard.services import DashboardService
from dbs.manager.envfiles.serializers import (
    EnvComparisonSerializer,
    EnvPulledSerializer,
    EnvVersionSerializer,
)
from dbs.manager.envfiles.services import EnvFileService
from dbs.manager.files.serializers import FileEntrySerializer
from dbs.manager.files.services import FileService
from dbs.manager.mcp.protocol import Tool
from dbs.manager.redeploy.serializers import RedeploySerializer, RevertSerializer
from dbs.manager.redeploy.services import RedeployService
from dbs.manager.servers.models import Server
from dbs.manager.servers.serializers import (
    AddedServerSerializer,
    HostKeyConfirmationSerializer,
    ServerCreateSerializer,
    ServerListSerializer,
    ServerSerializer,
    ServerUpdateSerializer,
)
from dbs.manager.servers.serializers.browse import BrowseEntrySerializer
from dbs.manager.servers.services import (
    BrowseService,
    DiscoveryService,
    HostKeyConfirmationService,
    ServerService,
)

Arguments = Mapping[str, Any]

ACTIVITY_LIMIT = 20
ACTIVITY_LIMIT_MAX = 200
DEFAULT_PORT = 22
AUTH_METHODS = ("password", "key_file", "generate_key")
SETTING_FIELDS = (
    "runtime",
    "compose_service",
    "compose_files",
    "project_dir",
    "python_path",
    "manage_path",
    "settings_module",
    "remote_backup_dir",
    "env_path",
    "file_roots",
)

TEXT = {"type": "string"}
SERVER = {"type": "string", "description": "The server's name or id."}
SERVERS = {
    "type": "array",
    "items": SERVER,
    "description": "The servers by name or id. Leave empty and set all to use every server.",
}
EVERY = {"type": "boolean", "description": "Use every server instead of naming them."}
BACKUP = {"type": "string", "description": "The backup's id, from list_backups."}
PLAN = {"type": "string", "description": "The plan's id, from list_plans."}
VERSION = {
    "type": "string",
    "description": "A .env version's id, from list_env_versions.",
}
REMOTE_PATH = {"type": "string", "description": "An absolute path on the server."}
PORT = {"type": "integer", "minimum": 1, "maximum": 65535}
SETTINGS = {
    "runtime": {
        "type": "string",
        "enum": ["host", "compose"],
        "description": (
            "Where the project runs: host when manage.py runs on the server itself, "
            "compose when it runs in a Docker Compose service."
        ),
    },
    "compose_service": {
        "type": "string",
        "description": "For compose: the service that runs the project, such as backend.",
    },
    "compose_files": {
        "type": "array",
        "items": {"type": "string"},
        "description": "For compose: the files to pass to docker compose -f, in order.",
    },
    "project_dir": {
        "type": "string",
        "description": "The folder that holds manage.py; for compose, the compose file.",
    },
    "python_path": {
        "type": "string",
        "description": "The Python that has django-dbs; for compose, inside the service.",
    },
    "manage_path": {
        "type": "string",
        "description": "The manage.py to run; for compose, inside the service.",
    },
    "settings_module": {"type": "string", "description": "DJANGO_SETTINGS_MODULE."},
    "remote_backup_dir": {
        "type": "string",
        "description": "Where the server writes backups.",
    },
    "env_path": {"type": "string", "description": "The .env file to keep versions of."},
    "file_roots": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Folders the Files tab may open.",
    },
}
PLAN_FIELDS = {
    "paths": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Folders to archive, or the folder to collect from.",
    },
    "pattern": {"type": "string", "description": "Which file names to collect."},
    "interval_minutes": {
        "type": ["integer", "null"],
        "description": "Run every this many minutes; null runs only when asked.",
    },
    "keep": {
        "type": "integer",
        "minimum": 1,
        "maximum": 5,
        "description": "How many to keep here, 1 to 5.",
    },
    "keep_remote": {
        "type": "integer",
        "minimum": 0,
        "maximum": 5,
        "description": "How many to keep on the server, 0 to 5.",
    },
    "enabled": {"type": "boolean"},
}

KEEPS_FEWER = (
    "Keeping fewer backups than the plan keeps now deletes the oldest ones, so Claude "
    "cannot do it. Ask the person to change it in the manager's interface or with "
    "django_dbs plan edit in a terminal; it asks for their password."
)

SEALED_DOWNLOAD = (
    "The manager keeps this file encrypted and saving it here would decrypt it, so "
    "Claude cannot do it. Ask the person to download it in the manager's interface or "
    "with django_dbs backup download in a terminal; it asks for their password."
)

INSTRUCTIONS = (
    "These tools drive the DBS manager, which backs up the Django projects on the servers "
    "it knows over SSH. Start with manager_overview or list_servers. To add a server, call "
    "fingerprint_host, show the fingerprint to the person and ask them to confirm it on "
    "the manager's Servers page or with the confirm_with command in a terminal; once they "
    "have, call add_server with that confirmation. Taking a backup waits until it is done. "
    "A plan can be made to keep more backups here, never fewer. Restores, moves and "
    "reverts of a move here are always rehearsals: nothing on the server changes. A "
    "server's backup passphrase must never be changed, because older backups would no "
    "longer open; capture it only while adding a server, before its first backup. "
    "Revealing secrets, real restores, moves and reverts, pushing a .env, keeping fewer "
    "backups, saving a backup the manager keeps encrypted, and removing or deleting "
    "anything are not available here; the person does those in the manager's interface "
    "or terminal. When a tool says it needs the account password, tell the person to do "
    "it there."
)


def build(user: Any) -> list[Tool]:
    return Toolbox(user).tools()


class Toolbox:
    def __init__(self, user: Any) -> None:
        self.user = user

    def tools(self) -> list[Tool]:
        return [
            Tool(
                "manager_overview",
                "Overview",
                "Every server's last check, last backup, next planned run and failures in "
                "the last 7 days, plus the latest failures. The manager's dashboard.",
                {},
                self.overview,
                read_only=True,
            ),
            Tool(
                "list_servers",
                "List servers",
                "The servers the manager knows.",
                dict(
                    search={"type": "string", "description": "Part of a name or host."}
                ),
                self.list_servers,
                read_only=True,
            ),
            Tool(
                "get_server",
                "Show a server",
                "One server's settings and its last check report. Never holds a secret.",
                dict(server=SERVER),
                self.get_server,
                required=("server",),
                read_only=True,
            ),
            Tool(
                "browse_server",
                "Browse a server",
                "List a folder on a server: names, kinds, sizes. Use it to find the "
                "project (a folder with manage.py) before add_server or update_server.",
                dict(server=SERVER, path=REMOTE_PATH),
                self.browse_server,
                required=("server",),
                read_only=True,
            ),
            Tool(
                "fingerprint_host",
                "Read a host key",
                "The SSH host key a machine offers, held for 10 minutes for a person to "
                "confirm. Show them the fingerprint and ask them to confirm it on the "
                "manager's Servers page, or by running the confirm_with command in a "
                "terminal. Only their confirmation lets add_server pin it.",
                dict(host=TEXT, port=PORT),
                self.fingerprint_host,
                required=("host",),
            ),
            Tool(
                "add_server",
                "Add a server",
                "Add a server, pinning the host key a person confirmed: pass the id "
                "fingerprint_host returned as confirmation, with the same host and port. "
                "auth_method is password (pass password), key_file (the path of a "
                "private key on this computer, read by the manager), or generate_key (a new "
                "key: show the person the authorized_keys line it returns). Then it finds "
                "the project and the Python with django-dbs, saves them and checks the "
                "server, unless discover is false. A password passes through this chat.",
                dict(
                    name={"type": "string", "description": "A name for the server."},
                    host=TEXT,
                    port=PORT,
                    username={"type": "string", "description": "The SSH account."},
                    confirmation={
                        "type": "string",
                        "description": "The id fingerprint_host returned, once a person "
                        "confirmed the fingerprint.",
                    },
                    auth_method={"type": "string", "enum": list(AUTH_METHODS)},
                    password={"type": "string", "description": "The SSH password."},
                    key_file={
                        "type": "string",
                        "description": "A private key file path here.",
                    },
                    key_passphrase={
                        "type": "string",
                        "description": "Unlocks key_file.",
                    },
                    discover={
                        "type": "boolean",
                        "description": "Find the project. Defaults to true.",
                    },
                    **SETTINGS,
                ),
                self.add_server,
                required=("name", "host", "username", "confirmation", "auth_method"),
            ),
            Tool(
                "update_server",
                "Change a server",
                "Change a server's name, address or project settings. Once a server's "
                "check has passed, changing its paths needs the account password, which "
                "this tool never takes: it says so, and the person does it in the manager.",
                dict(
                    server=SERVER,
                    name=TEXT,
                    host=TEXT,
                    port=PORT,
                    username=TEXT,
                    **SETTINGS,
                ),
                self.update_server,
                required=("server",),
            ),
            Tool(
                "check_servers",
                "Check servers",
                "Connect to servers and check they are ready: SSH, django-dbs, manage.py, "
                "the backup folder. Each result names what is wrong.",
                dict(servers=SERVERS, all=EVERY),
                self.check_servers,
                idempotent=True,
            ),
            Tool(
                "discover_server",
                "Find a project",
                "Look for the Django project and the Python that has django-dbs. "
                "With save, write what it found to the server.",
                dict(
                    server=SERVER,
                    project_dir={
                        "type": "string",
                        "description": "Look in this folder only.",
                    },
                    save={"type": "boolean"},
                ),
                self.discover_server,
                required=("server",),
            ),
            Tool(
                "capture_passphrase",
                "Store the backup passphrase",
                "Read the server's backup passphrase from the server and store it, "
                "encrypted. It is never returned. Use it only while adding a server, "
                "before its first backup: a server's backup passphrase must never be "
                "changed, because older backups would no longer open.",
                dict(server=SERVER),
                self.capture_passphrase,
                required=("server",),
                idempotent=True,
            ),
            Tool(
                "list_backups",
                "List backups",
                "The backups the manager holds, newest first.",
                dict(server=SERVER),
                self.list_backups,
                read_only=True,
            ),
            Tool(
                "take_backups",
                "Take backups",
                "Take a backup of each server, one after another, and wait for each. "
                "The manager first collects the backups waiting on the server, then "
                "streams a fresh one to itself. When the connection breaks, the result "
                "says kept_on_server: the server keeps that backup and the next take "
                "collects it. A server already backing up is reported, not waited for.",
                dict(servers=SERVERS, all=EVERY),
                self.take_backups,
            ),
            Tool(
                "verify_backup",
                "Verify a backup",
                "Open a backup end to end and check it is whole.",
                dict(backup=BACKUP),
                self.verify_backup,
                required=("backup",),
                idempotent=True,
            ),
            Tool(
                "rehearse_restore",
                "Rehearse a restore",
                "Restore a backup in a transaction that is rolled back, to prove it would "
                "work. Nothing on the server changes. A real restore is done by the person.",
                dict(
                    backup=BACKUP,
                    mode={"type": "string", "enum": ["merge", "replace"]},
                    target_server={
                        **SERVER,
                        "description": "Rehearse onto this server instead.",
                    },
                ),
                self.rehearse_restore,
                required=("backup", "mode"),
                idempotent=True,
            ),
            Tool(
                "download_backup",
                "Save a backup here",
                "Save a django-dbs backup to this computer, readable by its owner alone. "
                "path is an absolute file or folder; an existing file is never "
                "overwritten. Folder archives, collected and uploaded files are kept "
                "encrypted by the manager and saving one decrypts it, so this tool "
                "refuses them: the person downloads those in the manager.",
                dict(backup=BACKUP, path={"type": "string"}),
                self.download_backup,
                required=("backup", "path"),
            ),
            Tool(
                "list_plans",
                "List plans",
                "Backup plans that run on their own.",
                dict(server=SERVER),
                self.list_plans,
                read_only=True,
            ),
            Tool(
                "get_plan",
                "Show a plan",
                "One plan.",
                dict(plan=PLAN),
                self.get_plan,
                required=("plan",),
                read_only=True,
            ),
            Tool(
                "add_plan",
                "Add a plan",
                "Add a plan. kind dbs takes a django-dbs backup; archive and collect plans "
                "need the account password, which this tool never takes.",
                dict(
                    server=SERVER,
                    name=TEXT,
                    kind={"type": "string", "enum": ["dbs", "archive", "collect"]},
                    **PLAN_FIELDS,
                ),
                self.add_plan,
                required=("server", "name", "kind"),
            ),
            Tool(
                "update_plan",
                "Change a plan",
                "Change a plan's name or schedule, switch it on or off, or keep more "
                "backups. Keeping fewer deletes the oldest backups on the next run, so "
                "this tool refuses it: the person does it in the manager.",
                dict(plan=PLAN, name=TEXT, **PLAN_FIELDS),
                self.update_plan,
                required=("plan",),
            ),
            Tool(
                "run_plan",
                "Run a plan",
                "Run a plan now and wait for it.",
                dict(plan=PLAN),
                self.run_plan,
                required=("plan",),
            ),
            Tool(
                "list_activity",
                "List activity",
                "What the manager did, newest first, and who did it.",
                dict(
                    server=SERVER,
                    action={
                        "type": "string",
                        "description": "For example backup.take.",
                    },
                    status={
                        "type": "string",
                        "enum": ["queued", "running", "succeeded", "failed"],
                    },
                    limit={
                        "type": "integer",
                        "minimum": 1,
                        "maximum": ACTIVITY_LIMIT_MAX,
                    },
                ),
                self.list_activity,
                read_only=True,
            ),
            Tool(
                "get_activity",
                "Show an activity entry",
                "One entry of the activity log.",
                dict(entry={"type": "integer", "description": "The entry's number."}),
                self.get_activity,
                required=("entry",),
                read_only=True,
            ),
            Tool(
                "list_env_versions",
                "List .env versions",
                "The kept versions of a server's .env file: when, size and key names. "
                "Never values.",
                dict(server=SERVER),
                self.list_env_versions,
                required=("server",),
                read_only=True,
            ),
            Tool(
                "pull_env",
                "Keep the .env",
                "Keep the server's .env file as it is now, encrypted. Returns its key names, "
                "never values.",
                dict(server=SERVER),
                self.pull_env,
                required=("server",),
                idempotent=True,
            ),
            Tool(
                "compare_env_versions",
                "Compare .env versions",
                "Which keys were added, removed or changed between two versions. Never values.",
                dict(version=VERSION, other=VERSION),
                self.compare_env_versions,
                required=("version", "other"),
                read_only=True,
            ),
            Tool(
                "list_files",
                "List server files",
                "List a folder inside the server's allowed folders.",
                dict(server=SERVER, path=REMOTE_PATH),
                self.list_files,
                required=("server",),
                read_only=True,
            ),
            Tool(
                "rehearse_redeploy",
                "Rehearse a move",
                "Check that a project could move onto a new server with the same "
                "environment: the new server is checked, the old one is asked whether it "
                "answers, and a backup is restored in a transaction that is rolled back. "
                "Nothing changes on either server. A real move is done by the person.",
                dict(
                    source_server=SERVER,
                    target_server=SERVER,
                    backup={
                        **BACKUP,
                        "description": "The old server's backup to restore. Defaults "
                        "to its newest.",
                    },
                    env_version=VERSION,
                    flush={"type": "boolean"},
                ),
                self.rehearse_redeploy,
                required=("source_server", "target_server"),
                idempotent=True,
            ),
            Tool(
                "rehearse_revert",
                "Rehearse putting a new server back",
                "For a move that stopped after it changed the new server, rehearse "
                "restoring the new server's safety backup. Nothing changes. Putting the "
                "server back for real is done by the person.",
                dict(
                    move={
                        "type": "integer",
                        "description": "The move's activity number.",
                    }
                ),
                self.rehearse_revert,
                required=("move",),
                idempotent=True,
            ),
        ]

    def overview(self, arguments: Arguments) -> dict[str, Any]:
        return DashboardSerializer(DashboardService(self.user).summary()).data

    def list_servers(self, arguments: Arguments) -> dict[str, Any]:
        found = ServerService(self.user).list(arguments.get("search")).order_by("name")
        return {"results": ServerListSerializer(found, many=True).data}

    def get_server(self, arguments: Arguments) -> dict[str, Any]:
        return ServerSerializer(self._server(arguments["server"])).data

    def browse_server(self, arguments: Arguments) -> dict[str, Any]:
        server = self._server(arguments["server"])
        folder = BrowseService(self.user).list(server.pk, arguments.get("path") or None)
        entries = BrowseEntrySerializer(folder.entries, many=True).data
        return {
            "path": folder.path,
            "parent": folder.parent,
            "home": folder.home,
            "project": folder.project,
            "truncated": folder.truncated,
            "count": len(entries),
            "results": entries,
        }

    def fingerprint_host(self, arguments: Arguments) -> dict[str, Any]:
        held = HostKeyConfirmationService(self.user).request(
            arguments["host"], arguments.get("port") or DEFAULT_PORT
        )
        return {
            **HostKeyConfirmationSerializer(held).data,
            "confirm_with": f"django_dbs server confirm-host-key {held.id}",
        }

    def add_server(self, arguments: Arguments) -> dict[str, Any]:
        given = {
            field: arguments[field] for field in SETTING_FIELDS if field in arguments
        }
        port = arguments.get("port") or DEFAULT_PORT
        confirmation = str(arguments["confirmation"])
        confirmations = HostKeyConfirmationService(self.user)
        body: dict[str, Any] = {
            "name": arguments["name"],
            "host": arguments["host"],
            "port": port,
            "username": arguments["username"],
            "host_key": confirmations.approved(confirmation, arguments["host"], port),
            **_auth(arguments),
            **given,
        }
        added = ServerService(self.user).add(**validated(ServerCreateSerializer, body))
        confirmations.settle(confirmation)
        answer = dict(AddedServerSerializer(added).data)
        if added.public_key:
            return answer
        server = added.server
        if arguments.get("discover", True):
            settled = servers.settle(
                self.user, server, arguments.get("project_dir"), given
            )
            server = settled.server
            answer["discovery"] = settled.found or {"error": settled.error}
        [check] = servers.checked(self.user, [server])
        return {
            **answer,
            **ServerSerializer(server).data,
            "check": {"status": check.status, "problem": check.problem, **check.result},
        }

    def update_server(self, arguments: Arguments) -> dict[str, Any]:
        server = self._server(arguments["server"])
        changes = {key: value for key, value in arguments.items() if key != "server"}
        if not changes:
            raise AdapterError("name at least one setting to change.")
        data = validated(ServerUpdateSerializer, changes, partial=True)
        return ServerSerializer(ServerService(self.user).update(server.pk, **data)).data

    def check_servers(self, arguments: Arguments) -> dict[str, Any]:
        chosen = self._servers(arguments)
        return {
            "results": [
                {"status": item.status, "problem": item.problem, **item.result}
                for item in servers.checked(self.user, chosen)
            ]
        }

    def discover_server(self, arguments: Arguments) -> dict[str, Any]:
        server = self._server(arguments["server"])
        project = arguments.get("project_dir") or None
        if arguments.get("save"):
            settled = servers.settle(self.user, server, project, ())
            if settled.error:
                raise AdapterError(settled.error)
            return {**(settled.found or {}), "saved": True}
        return DiscoveryService(self.user).discover(server.pk, project_dir=project)

    def capture_passphrase(self, arguments: Arguments) -> dict[str, Any]:
        server = self._server(arguments["server"])
        ServerService(self.user).capture_passphrase(server.pk)
        return {"captured": True}

    def list_backups(self, arguments: Arguments) -> dict[str, Any]:
        service = BackupService(self.user)
        return {
            "results": [
                row
                for server in self._listed(arguments)
                for row in BackupFileSerializer(service.list(server.pk), many=True).data
            ]
        }

    def take_backups(self, arguments: Arguments) -> dict[str, Any]:
        taken = backups.take(self.user, self._servers(arguments))
        return {"results": [item.as_dict() for item in taken]}

    def verify_backup(self, arguments: Arguments) -> dict[str, Any]:
        file_id = references.identifier(arguments["backup"], "backup")
        return self._job(BackupService(self.user).verify(file_id))

    def rehearse_restore(self, arguments: Arguments) -> dict[str, Any]:
        file_id = references.identifier(arguments["backup"], "backup")
        body: dict[str, Any] = {"mode": arguments["mode"], "rehearse": True}
        if arguments.get("target_server"):
            body["target_server"] = self._server(arguments["target_server"]).pk
        data = validated(RestoreSerializer, body)
        return self._job(BackupService(self.user).restore(file_id, **data))

    def download_backup(self, arguments: Arguments) -> dict[str, Any]:
        file_id = references.identifier(arguments["backup"], "backup")
        target = Path(arguments["path"]).expanduser()
        if not target.is_absolute():
            raise AdapterError("path must be absolute.")
        if BackupService(self.user).get(file_id).sealed:
            raise AdapterError(SEALED_DOWNLOAD)
        target = backups.save(self.user, file_id, target)
        return {"path": str(target), "size": os.path.getsize(target)}

    def list_plans(self, arguments: Arguments) -> dict[str, Any]:
        service = BackupPlanService(self.user)
        return {
            "results": [
                {**row, "server_name": server.name}
                for server in self._listed(arguments)
                for row in BackupPlanSerializer(service.list(server.pk), many=True).data
            ]
        }

    def get_plan(self, arguments: Arguments) -> dict[str, Any]:
        plan_id = references.identifier(arguments["plan"], "plan")
        return BackupPlanSerializer(BackupPlanService(self.user).get(plan_id)).data

    def add_plan(self, arguments: Arguments) -> dict[str, Any]:
        server = self._server(arguments["server"])
        body = {**arguments, "server": server.pk}
        data = validated(PlanCreateSerializer, body)
        return BackupPlanSerializer(BackupPlanService(self.user).create(**data)).data

    def update_plan(self, arguments: Arguments) -> dict[str, Any]:
        plan_id = references.identifier(arguments["plan"], "plan")
        changes = {key: value for key, value in arguments.items() if key != "plan"}
        if not changes:
            raise AdapterError("name at least one thing to change.")
        data = validated(PlanUpdateSerializer, changes, partial=True)
        service = BackupPlanService(self.user)
        if service.keeps_fewer(plan_id, data):
            raise AdapterError(KEEPS_FEWER)
        return BackupPlanSerializer(service.update(plan_id, **data)).data

    def run_plan(self, arguments: Arguments) -> dict[str, Any]:
        plan_id = references.identifier(arguments["plan"], "plan")
        return self._job(BackupPlanService(self.user).run(plan_id))

    def list_activity(self, arguments: Arguments) -> dict[str, Any]:
        body = {
            key: arguments[key] for key in ("action", "status") if arguments.get(key)
        }
        if arguments.get("server"):
            body["server"] = self._server(arguments["server"]).pk
        limit = arguments.get("limit") or ACTIVITY_LIMIT
        service = ActivityService(self.user)
        entries = list(
            service.list(**validated(ActivityFilterSerializer, body))[:limit]
        )
        context = {"servers": service.servers_for(entries)}
        return {"results": ActivitySerializer(entries, many=True, context=context).data}

    def get_activity(self, arguments: Arguments) -> dict[str, Any]:
        entry = ActivityService(self.user).get(int(arguments["entry"]))
        return jobs.described(self.user, entry)

    def list_env_versions(self, arguments: Arguments) -> dict[str, Any]:
        server = self._server(arguments["server"])
        versions = EnvFileService(self.user).list(server.pk)
        return {"results": EnvVersionSerializer(versions, many=True).data}

    def pull_env(self, arguments: Arguments) -> dict[str, Any]:
        server = self._server(arguments["server"])
        return EnvPulledSerializer(EnvFileService(self.user).pull(server.pk)).data

    def compare_env_versions(self, arguments: Arguments) -> dict[str, Any]:
        first = references.identifier(arguments["version"], "version")
        other = references.identifier(arguments["other"], "version")
        return EnvComparisonSerializer(
            EnvFileService(self.user).compare(first, other)
        ).data

    def list_files(self, arguments: Arguments) -> dict[str, Any]:
        server = self._server(arguments["server"])
        folder = FileService(self.user).list(server.pk, arguments.get("path") or None)
        entries = FileEntrySerializer(folder.entries, many=True).data
        return {
            "path": folder.path,
            "parent": folder.parent,
            "root": folder.root,
            "roots": folder.roots,
            "count": len(entries),
            "results": entries,
        }

    def rehearse_redeploy(self, arguments: Arguments) -> dict[str, Any]:
        body: dict[str, Any] = {
            "source_server": self._server(arguments["source_server"]).pk,
            "target_server": self._server(arguments["target_server"]).pk,
            "flush": bool(arguments.get("flush")),
            "rehearsal": True,
        }
        if arguments.get("backup"):
            body["backup"] = references.identifier(arguments["backup"], "backup")
        if arguments.get("env_version"):
            body["env_version"] = references.identifier(
                arguments["env_version"], "version"
            )
        data = validated(RedeploySerializer, body)
        return self._job(RedeployService(self.user).start(**data))

    def rehearse_revert(self, arguments: Arguments) -> dict[str, Any]:
        move = references.number(str(arguments["move"]), "move")
        data = validated(RevertSerializer, {"rehearsal": True})
        return self._job(RedeployService(self.user).revert(move, **data))

    def _server(self, reference: Any) -> Server:
        return references.server(self.user, str(reference))

    def _servers(self, arguments: Arguments) -> list[Server]:
        named = [str(reference) for reference in arguments.get("servers") or []]
        return references.servers(self.user, named, bool(arguments.get("all")))

    def _listed(self, arguments: Arguments) -> list[Server]:
        if arguments.get("server"):
            return [self._server(arguments["server"])]
        return list(ServerService(self.user).list().order_by("name"))

    def _job(self, job: Any) -> dict[str, Any]:
        entry = jobs.finished(self.user, job)
        described = jobs.described(self.user, entry)
        if jobs.succeeded(entry):
            return {"ok": True, "activity": described}
        return {"ok": False, "error": jobs.failure(entry), "activity": described}


def _auth(arguments: Arguments) -> dict[str, Any]:
    method = arguments["auth_method"]
    if method == "generate_key":
        return {"generate_key": True}
    if method == "password":
        if not arguments.get("password"):
            raise AdapterError("auth_method password needs password.")
        return {
            "auth_method": Server.AuthMethod.PASSWORD,
            "password": arguments["password"],
        }
    if method == "key_file":
        if not arguments.get("key_file"):
            raise AdapterError("auth_method key_file needs key_file.")
        try:
            private_key = (
                Path(arguments["key_file"]).expanduser().read_text(encoding="utf-8")
            )
        except (OSError, UnicodeDecodeError) as exc:
            raise AdapterError(
                f"could not read {arguments['key_file']}: {exc}"
            ) from exc
        auth = {"auth_method": Server.AuthMethod.KEY, "private_key": private_key}
        if arguments.get("key_passphrase"):
            auth["key_passphrase"] = arguments["key_passphrase"]
        return auth
    raise AdapterError(f"auth_method is one of {', '.join(AUTH_METHODS)}.")
