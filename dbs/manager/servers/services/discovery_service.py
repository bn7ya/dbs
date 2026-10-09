from __future__ import annotations

import json
import posixpath
import re
from typing import Any
from uuid import UUID

from rest_framework.exceptions import APIException

from dbs.manager.activity.services import ActivityService
from dbs.manager.servers.gateways import EntryKind, RemoteHost
from dbs.manager.servers.models import DEFAULT_REMOTE_BACKUP_DIR, Server
from dbs.manager.servers.services.connection_service import ServerConnectionService
from dbs.manager.servers.services.server_service import ServerService

SEARCH_ROOTS = ("~", "/srv", "/var/www", "/opt")
SEARCH_DEPTH = 2
ENTRIES_PER_FOLDER = 500
MANAGE = "manage.py"
PYTHON_CANDIDATES = (".venv/bin/python", "venv/bin/python", "env/bin/python")
BARE_PYTHON = "python3"
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

    def discover(self, server_id: UUID) -> dict[str, Any]:
        server = self.servers.get(server_id)
        with self.activity.track(DISCOVER, server=server, target=server.name) as entry:
            with self.connections.open(server) as remote:
                found = self._found(server, remote)
            entry.detail = {
                "project_dir": found["project_dir"],
                "dbs_version": found["dbs_version"],
            }
            return found

    def _found(self, server: Server, remote: RemoteHost) -> dict[str, Any]:
        projects = project_dirs(remote)
        project = projects[0] if projects else ""
        pythons = python_paths(remote, project) if project else [BARE_PYTHON]
        found = {
            "project_dir": project,
            "python_path": pythons[0],
            "manage_path": MANAGE,
            "settings_module": settings_module(remote, project) if project else "",
            "remote_backup_dir": server.remote_backup_dir or DEFAULT_REMOTE_BACKUP_DIR,
            "file_roots": [],
            "env_path": env_path(remote, project) if project else "",
            "dbs_version": None,
        }
        if project:
            found.update(connection_details(remote, found))
        found["candidates"] = {"project_dirs": projects, "python_paths": pythons}
        return found


def _quiet(call, *args, default=None):
    try:
        return call(*args)
    except APIException:
        return default


def project_dirs(remote: RemoteHost) -> list[str]:
    home = _quiet(remote.realpath, ".")
    found: list[str] = []
    for root in SEARCH_ROOTS:
        start = home if root == "~" else root
        if start:
            _search(remote, start, SEARCH_DEPTH, found)
    return list(dict.fromkeys(found))


def _search(remote: RemoteHost, folder: str, depth: int, found: list[str]) -> None:
    entries = _quiet(remote.listdir, folder, default=[])
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


def python_paths(remote: RemoteHost, project: str) -> list[str]:
    candidates = [posixpath.join(project, relative) for relative in PYTHON_CANDIDATES]
    existing = [
        path for path in candidates if _quiet(remote.exists, path, default=False)
    ]
    return [*existing, BARE_PYTHON]


def settings_module(remote: RemoteHost, project: str) -> str:
    content = _quiet(
        remote.read_small, posixpath.join(project, MANAGE), MANAGE_MAX_BYTES
    )
    if not content:
        return ""
    match = SETTINGS_MODULE.search(content.decode("utf-8", errors="replace"))
    return match.group(1) if match else ""


def env_path(remote: RemoteHost, project: str) -> str:
    path = posixpath.join(project, ".env")
    return path if _quiet(remote.exists, path, default=False) else ""


def connection_details(remote: RemoteHost, found: dict[str, Any]) -> dict[str, Any]:
    env = (
        {"DJANGO_SETTINGS_MODULE": found["settings_module"]}
        if found["settings_module"]
        else None
    )
    result = _quiet(
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
