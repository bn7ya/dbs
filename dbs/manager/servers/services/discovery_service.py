from __future__ import annotations

import json
import posixpath
import re
from typing import Any
from uuid import UUID

from dbs.manager.activity.services import ActivityService
from dbs.manager.servers.gateways import EntryKind, RemoteHost
from dbs.manager.servers.models import DEFAULT_REMOTE_BACKUP_DIR, Server
from dbs.manager.servers.services import pythons
from dbs.manager.servers.services.connection_service import ServerConnectionService
from dbs.manager.servers.services.pythons import quiet
from dbs.manager.servers.services.server_service import ServerService

SEARCH_ROOTS = ("~", "/srv", "/var/www", "/opt")
SEARCH_DEPTH = 2
ENTRIES_PER_FOLDER = 500
MANAGE = "manage.py"
MANAGE_MAX_BYTES = 64 * 1024
SETTINGS_MODULE = re.compile(
    "DJANGO_SETTINGS_MODULE[\"']\\s*,\\s*[\"']([A-Za-z_][\\w.]*)[\"']"
)
CONNECTION_KEYS = (
    "project_dir",
    "python_path",
    "manage_path",
    "settings_module",
    "remote_backup_dir",
    "file_roots",
    "env_path",
    "dbs_version",
)
DISCOVER = "server.discover"


class DiscoveryService:
    def __init__(self, user: Any) -> None:
        self.user = user
        self.servers = ServerService(user)
        self.connections = ServerConnectionService(user)
        self.activity = ActivityService(user)

    def discover(
        self,
        server_id: UUID,
        project_dir: str | None = None,
        account_password: str = "",
    ) -> dict[str, Any]:
        server = self.servers.get(server_id)
        self.servers.require_step_up(server, account_password)
        with self.activity.track(DISCOVER, server=server, target=server.name) as entry:
            self.servers.confirm_step_up(account_password)
            with self.connections.open(server) as remote:
                found = self._found(server, remote, project_dir)
            entry.detail = {
                "project_dir": found["project_dir"],
                "dbs_version": found["dbs_version"],
            }
            return found

    def _found(
        self, server: Server, remote: RemoteHost, chosen: str | None
    ) -> dict[str, Any]:
        projects = [chosen] if chosen else project_dirs(remote)
        project = projects[0] if projects else ""
        candidates = pythons.candidates(remote, project)
        usable = pythons.with_dbs(remote, candidates, project or None)
        found = {
            "project_dir": project,
            "python_path": usable.python_path if usable else candidates[0],
            "manage_path": MANAGE,
            "settings_module": settings_module(remote, project) if project else "",
            "remote_backup_dir": server.remote_backup_dir or DEFAULT_REMOTE_BACKUP_DIR,
            "file_roots": [],
            "env_path": env_path(remote, project) if project else "",
            "dbs_version": usable.dbs_version if usable else None,
            "is_project": bool(project) and is_project(remote, project),
        }
        if project and (chosen or pythons.trusted_with_parent(remote, project)):
            found.update(connection_details(remote, found))
        found["candidates"] = {"project_dirs": projects, "python_paths": candidates}
        return found


def discovered_settings(found: dict[str, Any], chosen: bool) -> dict[str, Any]:
    settings: dict[str, Any] = {
        field: found[field]
        for field in ("project_dir", "manage_path", "remote_backup_dir", "file_roots")
        if found.get(field)
    }
    if found.get("python_path") and (found.get("dbs_version") is not None or chosen):
        settings["python_path"] = found["python_path"]
    for field in ("settings_module", "env_path"):
        if chosen or found.get(field):
            settings[field] = found.get(field) or ""
    return settings


def project_dirs(remote: RemoteHost) -> list[str]:
    home = quiet(remote.realpath, ".")
    found: list[str] = []
    for root in SEARCH_ROOTS:
        start = home if root == "~" else root
        if start:
            _search(remote, start, SEARCH_DEPTH, found)
    return list(dict.fromkeys(found))


def _search(remote: RemoteHost, folder: str, depth: int, found: list[str]) -> None:
    entries = quiet(remote.listdir, folder, default=[])
    names = {entry.name: entry for entry in entries[:ENTRIES_PER_FOLDER]}
    manage = names.get(MANAGE)
    if manage is not None and manage.kind == EntryKind.FILE:
        found.append(folder)
    if depth == 0:
        return
    for name in sorted(names):
        entry = names[name]
        if entry.kind == EntryKind.FOLDER and not name.startswith("."):
            _search(remote, posixpath.join(folder, name), depth - 1, found)


def is_project(remote: RemoteHost, folder: str) -> bool:
    return bool(quiet(remote.exists, posixpath.join(folder, MANAGE), default=False))


def settings_module(remote: RemoteHost, project: str) -> str:
    content = quiet(
        remote.read_small, posixpath.join(project, MANAGE), MANAGE_MAX_BYTES
    )
    if not content:
        return ""
    match = SETTINGS_MODULE.search(content.decode("utf-8", errors="replace"))
    return match.group(1) if match else ""


def env_path(remote: RemoteHost, project: str) -> str:
    path = posixpath.join(project, ".env")
    return path if quiet(remote.exists, path, default=False) else ""


def connection_details(remote: RemoteHost, found: dict[str, Any]) -> dict[str, Any]:
    env = (
        {"DJANGO_SETTINGS_MODULE": found["settings_module"]}
        if found["settings_module"]
        else None
    )
    result = quiet(
        lambda: remote.run(
            [found["python_path"], found["manage_path"], "dbs", "connection", "--json"],
            cwd=found["project_dir"],
            env=env,
        )
    )
    if result is None or not result.ok:
        return {}
    try:
        details = json.loads(result.stdout.strip() or "null")
    except ValueError:
        return {}
    if not isinstance(details, dict) or details.get("dbs_connection") != 1:
        return {}
    preferred = {}
    for key in CONNECTION_KEYS:
        value = details.get(key)
        if key == "file_roots":
            if isinstance(value, list) and all(isinstance(root, str) for root in value):
                preferred[key] = value
        elif isinstance(value, str) and value:
            preferred[key] = value
    return preferred
