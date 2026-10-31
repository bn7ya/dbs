from __future__ import annotations

import json
import posixpath
import re
from typing import Any
from uuid import UUID

from dbs.manager.accounts.services import AccountService
from dbs.manager.activity.services import ActivityService
from dbs.manager.applications import deployment
from dbs.manager.applications.models import Application
from dbs.manager.applications.paths import on_host
from dbs.manager.applications.services import facts as found_facts
from dbs.manager.applications.serializers.application import (
    COMPOSE_FILE,
    COMPOSE_NAME,
    CONTAINER_NAME,
)
from dbs.manager.servers import versions
from dbs.manager.servers.gateways import (
    ENGINES,
    ContainerTarget,
    DbsProfile,
    EntryKind,
    RemoteHost,
)
from dbs.manager.servers.services import pythons
from dbs.manager.servers.services.connection_service import ServerConnectionService
from dbs.manager.servers.services.pythons import quiet
from dbs.manager.servers.services.server_service import (
    ServerService,
    engine_report,
    require_account_password,
)
from dbs.manager.permissions import Capability, requires

SEARCH_ROOTS = ("~", "/srv", "/var/www", "/opt")
SEARCH_DEPTH = 2
ENTRIES_PER_FOLDER = 500
MANAGE = "manage.py"
COMPOSE_FILES = (
    "compose.yaml",
    "compose.yml",
    "docker-compose.yaml",
    "docker-compose.yml",
    "podman-compose.yaml",
    "podman-compose.yml",
)
CONTAINER_FILES = ("Dockerfile", "Containerfile")
ENV_SUFFIX = ".env"
CONTAINERS_INSPECTED = 30
INSPECTED_FIELDS = (
    '{"Name":{{json .Name}},"Image":{{json .Image}},'
    '"State":{"Running":{{json .State.Running}}},'
    '"Config":{"Image":{{json .Config.Image}},"Labels":{{json .Config.Labels}},'
    '"WorkingDir":{{json .Config.WorkingDir}},"Env":{{json .Config.Env}}},'
    '"Mounts":{{json .Mounts}}}'
)
CANDIDATES_PROBED = 8
MANAGE_MAX_BYTES = 64 * 1024
COMPOSE_MAX_BYTES = 256 * 1024
CONTAINER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
SETTINGS_MODULE = re.compile(
    "DJANGO_SETTINGS_MODULE[\"']\\s*,\\s*[\"']([A-Za-z_][\\w.]*)[\"']"
)
ENV_FILE_LINE = re.compile(r"^(\s*)env_file:\s*(.*)$")
LIST_ITEM = re.compile(r"^(\s*)-\s*(.+)$")
COMPOSE_LABEL = "com.docker.compose."
PODMAN_COMPOSE_LABEL = "io.podman.compose."
PROJECT_FOLDERS = ("/app", "/code", "/srv", "/usr/src/app", "/opt/app")
DISCOVER = "application.discover"
ANSWER_WEIGHTS = {"runs_in": 4, "engine": 1, "database": 1}
ACCOUNT_PASSWORD_REQUIRED = "Enter your own password to search this server."
CONNECTION_KEYS = (
    "settings_module",
    "remote_backup_dir",
    "file_roots",
    "env_path",
    "dbs_version",
)
FIND_PROJECT = """
import json, os, re, sys
pattern = re.compile(r"DJANGO_SETTINGS_MODULE[\\"']\\s*,\\s*[\\"']([A-Za-z_][\\w.]*)[\\"']")

def settings_of(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            found = pattern.search(fh.read(65536))
    except OSError:
        return ""
    return found.group(1) if found else ""

def names(folder):
    try:
        return sorted(os.listdir(folder))[:200]
    except OSError:
        return []

def folders(start):
    yield start
    for depth in (1, 2):
        stack = [start]
        for _ in range(depth):
            stack = [
                os.path.join(folder, name)
                for folder in stack
                for name in names(folder)
                if not name.startswith(".") and os.path.isdir(os.path.join(folder, name))
            ] if all(os.path.isdir(folder) for folder in stack) else []
        yield from stack

for start in sys.argv[1:]:
    if not start or not os.path.isdir(start):
        continue
    for folder in folders(start):
        manage = os.path.join(folder, "manage.py")
        if os.path.isfile(manage):
            print(json.dumps({"manage": manage, "folder": folder, "settings": settings_of(manage)}))
            sys.exit(0)
print("{}")
"""


class DiscoveryService:
    def __init__(self, user: Any) -> None:
        self.user = user
        self.servers = ServerService(user)
        self.connections = ServerConnectionService(user)
        self.activity = ActivityService(user)

    @requires(Capability.APPLICATIONS_MANAGE)
    def discover(
        self,
        server_id: UUID,
        folder: str = "",
        account_password: str = "",
        deployment: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        server = self.servers.get(server_id)
        if not account_password and not self.servers.in_setup(server):
            require_account_password("", ACCOUNT_PASSWORD_REQUIRED)
        with self.activity.track(
            DISCOVER, subject=server, target=folder or server.name
        ) as entry:
            if account_password:
                AccountService(self.user).confirm_password(account_password)
            with self.connections.open(server) as remote:
                report = Discovery(remote, deployment).run(folder)
            entry.detail = {
                "folder": report["folder"],
                "candidates": len(report["candidates"]),
            }
            return report


class Discovery:
    def __init__(
        self, remote: RemoteHost, answers: dict[str, str] | None = None
    ) -> None:
        self.remote = remote
        self.answers = dict(answers or {})
        self.neighbours: list[dict[str, Any]] = []
        self.services_found: list[dict[str, Any]] | None = None
        self.home = "/"

    def run(self, folder: str) -> dict[str, Any]:
        home = quiet(self.remote.realpath, ".") or "/"
        self.home = home
        chosen = quiet(self.remote.realpath, folder) if folder else None
        if not chosen:
            return {
                "folder": folder,
                "trusted": False,
                "listing": {},
                "engines": {},
                "candidates": [],
                "folders": project_folders(self.remote, home),
                "unread_containers": [],
            }
        trusted = pythons.trusted_with_parent(self.remote, chosen)
        listing = folder_listing(self.remote, chosen)
        report: dict[str, Any] = {
            "folder": chosen,
            "trusted": trusted,
            "listing": listing,
            "engines": {},
            "candidates": [],
            "folders": [],
            "unread_containers": [],
        }
        if not trusted:
            return report
        engines = {engine: engine_report(self.remote, engine) for engine in ENGINES}
        report["engines"] = engines
        compose_env = compose_env_files(self.remote, chosen, listing["compose_files"])
        listed = {
            engine: listed_containers(self.remote, engine, report["unread_containers"])
            for engine, facts in engines.items()
            if facts["usable"]
        }
        self.neighbours = [container for rows in listed.values() for container in rows]
        containers = [
            container
            for engine, rows in listed.items()
            for container in matched_containers(self.remote, engine, chosen, rows)
        ]
        candidates = [
            self.container_candidate(chosen, container, compose_env)
            for container in containers[:CANDIDATES_PROBED]
        ]
        if listing["manage"] or not candidates:
            host = self.host_candidate(chosen, listing)
            if host is not None:
                candidates.append(host)
        report["candidates"] = sorted(
            (self.with_facts(candidate) for candidate in candidates[:CANDIDATES_PROBED]),
            key=lambda found: -found["score"],
        )
        return report

    def with_facts(self, candidate: dict[str, Any]) -> dict[str, Any]:
        if self.services_found is None:
            self.services_found = found_facts.host_services(self.remote, self.home)
        project = candidate.get("compose_project") or ""
        facts = found_facts.facts_for(
            self.remote,
            candidate,
            database=candidate.pop("database_facts", None),
            services_found=self.services_found,
            project_services=[
                *candidate.pop("project_services", []),
                *(
                    neighbour["compose_service"]
                    for neighbour in self.neighbours
                    if project and neighbour["compose_project"] == project
                ),
            ],
            containers=[neighbour["name"] for neighbour in self.neighbours],
            image=candidate.pop("image", None),
        )
        detected = facts.pop("detected")
        candidate["facts"] = facts
        candidate["detected"] = detected
        candidate["mismatches"] = deployment.mismatches(self.answers, detected)
        candidate["score"] += answer_bonus(self.answers, detected)
        return candidate

    def host_candidate(
        self, folder: str, listing: dict[str, Any]
    ) -> dict[str, Any] | None:
        project = folder if listing["manage"] else nested_project(self.remote, folder)
        if not project:
            return None
        found_pythons = pythons.candidates(self.remote, project)
        runnable = project == folder or pythons.trusted_with_parent(self.remote, project)
        usable = (
            pythons.with_dbs(self.remote, found_pythons, host_profile(project))
            if runnable
            else None
        )
        candidate = {
            "kind": Application.Kind.HOST,
            "engine": "",
            "compose_project": "",
            "compose_service": "",
            "compose_files": [],
            "container_name": "",
            "replicas": 1,
            "running": True,
            "project_dir": project,
            "workdir": "",
            "python_path": usable.python_path if usable else found_pythons[0],
            "python_paths": found_pythons,
            "manage_path": MANAGE,
            "settings_module": settings_module(self.remote, project),
            "remote_backup_dir": "",
            "mounts": [],
            "file_roots": [],
            "env": host_env(self.remote, project, listing),
            "dbs_version": usable.dbs_version if usable else None,
        }
        if usable is not None:
            self.ask_dbs(candidate, host_profile(project, candidate))
        return scored(candidate)

    def container_candidate(
        self,
        folder: str,
        container: dict[str, Any],
        compose_env: list[str],
    ) -> dict[str, Any]:
        compose = bool(container["compose_service"])
        target = ContainerTarget(
            engine=container["engine"],
            service=container["compose_service"] if compose else "",
            files=tuple(container["compose_files"]) if compose else (),
            project=container["compose_project"] if compose else "",
            container="" if compose else container["name"],
        )
        project_dir = container["compose_dir"] or folder
        started_with = (
            compose_env_files(self.remote, project_dir, container["compose_files"])
            if compose
            else []
        )
        declared = (
            found_facts.compose_services(
                self.remote, project_dir, container["compose_files"], COMPOSE_MAX_BYTES
            )
            if compose
            else {}
        )
        candidate: dict[str, Any] = {
            "kind": Application.Kind.COMPOSE if compose else Application.Kind.CONTAINER,
            "engine": container["engine"],
            "compose_project": container["compose_project"] if compose else "",
            "compose_service": container["compose_service"] if compose else "",
            "compose_files": container["compose_files"] if compose else [],
            "container_name": "" if compose else container["name"],
            "replicas": container["replicas"],
            "running": container["running"],
            "project_dir": project_dir,
            "workdir": container["workdir"],
            "python_path": "",
            "python_paths": [],
            "manage_path": MANAGE,
            "settings_module": container["settings_module"],
            "remote_backup_dir": "",
            "mounts": container["mounts"],
            "file_roots": [],
            "env": [
                {"path": path, "location": "host", "source": "compose"}
                for path in dict.fromkeys([*compose_env, *started_with])
            ],
            "dbs_version": None,
            "image": {
                "ref": container["image"],
                "id": container["image_id"],
                "built_here": bool(
                    declared.get(container["compose_service"], {}).get("build")
                ),
            },
            "project_services": list(declared),
        }
        if not container["running"]:
            return scored(candidate)
        profile = DbsProfile(python="", manage=MANAGE, project_dir=project_dir, container=target)
        inside = [
            mount["destination"]
            for mount in container["mounts"]
            if mount.get("source") == folder
        ]
        found_pythons = pythons.container_pythons(container["workdir"], *container["pythons"])
        candidate["python_paths"] = found_pythons
        usable = pythons.with_dbs(self.remote, found_pythons, profile)
        if usable is None:
            candidate["python_path"] = found_pythons[0]
            return scored(candidate)
        candidate["python_path"] = usable.python_path
        candidate["dbs_version"] = usable.dbs_version
        project = find_project(
            self.remote,
            DbsProfile(python=usable.python_path, manage=MANAGE, project_dir=project_dir, container=target),
            [*inside, container["workdir"], *PROJECT_FOLDERS],
        )
        if project:
            candidate["manage_path"] = project["manage"]
            candidate["workdir"] = project["folder"]
            candidate["settings_module"] = (
                candidate["settings_module"] or project.get("settings") or ""
            )
        self.ask_dbs(candidate, container_profile(candidate, target))
        return scored(candidate)

    def ask_dbs(self, candidate: dict[str, Any], profile: DbsProfile) -> None:
        result = quiet(
            self.remote.run_manage, profile, ["dbs", "connection", "--json"]
        )
        if result is None or not result.ok:
            return
        details = _json_object(result.stdout)
        if details is None or details.get("dbs_connection") not in (1, 2):
            return
        for key in CONNECTION_KEYS:
            value = details.get(key)
            if key == "file_roots":
                if isinstance(value, list) and all(isinstance(root, str) for root in value):
                    candidate["file_roots"] = [
                        {"path": root, "on_host": translated(candidate, root)}
                        for root in value
                    ]
            elif key == "env_path":
                if isinstance(value, str) and value:
                    location = "container" if candidate["kind"] != Application.Kind.HOST else "host"
                    mapped = translated(candidate, value)
                    entry = (
                        {"path": mapped, "location": "host", "source": "dbs"}
                        if location == "container" and mapped
                        else {"path": value, "location": location, "source": "dbs"}
                    )
                    candidate["env"] = [entry, *candidate["env"]]
            elif isinstance(value, str) and value:
                candidate[key] = value
        candidate["backup_dir_on_host"] = translated(candidate, candidate["remote_backup_dir"])
        candidate["database_facts"] = found_facts.database_facts(self.remote, profile)


def answer_bonus(answers: dict[str, str], detected: dict[str, str]) -> int:
    return sum(
        weight
        for key, weight in ANSWER_WEIGHTS.items()
        if deployment.agreements({key: answers.get(key, "")}, detected)
    )


def scored(candidate: dict[str, Any]) -> dict[str, Any]:
    problems = []
    if not candidate["running"]:
        problems.append("container_not_running")
    if candidate["dbs_version"] is None:
        problems.append("dbs_missing")
    elif not versions.at_least(candidate["dbs_version"], versions.MINIMUM_REMOTE):
        problems.append("dbs_too_old")
    if candidate["kind"] != Application.Kind.HOST and candidate["remote_backup_dir"] and not translated(
        candidate, candidate["remote_backup_dir"]
    ):
        problems.append("backup_dir_not_mounted")
    candidate.setdefault("backup_dir_on_host", translated(candidate, candidate["remote_backup_dir"]))
    candidate["env"] = unique_env(candidate["env"])
    candidate["compatible"] = candidate["dbs_version"] is not None and "dbs_too_old" not in problems
    candidate["problems"] = problems
    candidate["score"] = (
        (10 if candidate["dbs_version"] else 0)
        + (3 if candidate["running"] else 0)
        + (2 if candidate["settings_module"] else 0)
        + (1 if candidate["kind"] != Application.Kind.HOST else 0)
        - len(problems)
    )
    return candidate


def translated(candidate: dict[str, Any], path: str) -> str | None:
    if not path:
        return None
    if candidate["kind"] == Application.Kind.HOST:
        return path
    return on_host(candidate["mounts"], path)


def unique_env(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    kept = []
    for entry in entries:
        key = (entry["path"], entry["location"])
        if entry["path"] and key not in seen:
            seen.add(key)
            kept.append(entry)
    return kept


def settings_of(candidate: dict[str, Any], name: str = "") -> dict[str, Any]:
    env = candidate["env"][0] if candidate.get("env") else None
    fields = {
        "kind": candidate["kind"],
        "engine": candidate["engine"],
        "compose_project": candidate["compose_project"],
        "compose_service": candidate["compose_service"],
        "compose_files": list(candidate["compose_files"]),
        "container_name": candidate["container_name"],
        "project_dir": candidate["project_dir"],
        "workdir": candidate["workdir"],
        "python_path": candidate["python_path"] or pythons.BARE_PYTHONS[0],
        "manage_path": candidate["manage_path"],
        "settings_module": candidate["settings_module"],
        "mounts": list(candidate["mounts"]),
        "file_roots": [root["path"] for root in candidate["file_roots"]],
        "env_path": env["path"] if env else "",
        "env_location": env["location"] if env else Application.EnvLocation.HOST,
    }
    if candidate["remote_backup_dir"]:
        fields["remote_backup_dir"] = candidate["remote_backup_dir"]
    if name:
        fields["name"] = name
    return fields


def host_profile(project: str, candidate: dict[str, Any] | None = None) -> DbsProfile:
    return DbsProfile(
        python=(candidate or {}).get("python_path") or "",
        manage=MANAGE,
        project_dir=project or None,
        settings_module=(candidate or {}).get("settings_module") or None,
    )


def container_profile(candidate: dict[str, Any], target: ContainerTarget) -> DbsProfile:
    workdir = candidate["workdir"]
    return DbsProfile(
        python=candidate["python_path"],
        manage=candidate["manage_path"],
        project_dir=candidate["project_dir"],
        settings_module=candidate["settings_module"] or None,
        container=ContainerTarget(
            engine=target.engine,
            service=target.service,
            files=target.files,
            project=target.project,
            container=target.container,
            workdir=workdir,
        ),
    )


def folder_listing(remote: RemoteHost, folder: str) -> dict[str, Any]:
    entries = quiet(remote.listdir, folder, default=[]) or []
    files = {
        entry.name for entry in entries[:ENTRIES_PER_FOLDER] if entry.kind == EntryKind.FILE
    }
    return {
        "manage": MANAGE in files,
        "compose_files": [name for name in COMPOSE_FILES if name in files],
        "container_files": [name for name in CONTAINER_FILES if name in files],
        "env_files": sorted(
            name for name in files if name == ENV_SUFFIX or name.startswith(".env.") or name.endswith(ENV_SUFFIX)
        ),
    }


def host_env(remote: RemoteHost, project: str, listing: dict[str, Any]) -> list[dict[str, Any]]:
    names = listing["env_files"] if listing.get("manage") else folder_listing(remote, project)["env_files"]
    return [
        {"path": posixpath.join(project, name), "location": "host", "source": "folder"}
        for name in names
    ]


def nested_project(remote: RemoteHost, folder: str) -> str:
    found: list[str] = []
    _search(remote, folder, 1, found, [])
    return found[0] if found else ""


def compose_env_files(
    remote: RemoteHost, folder: str, compose_files: list[str]
) -> list[str]:
    found: list[str] = []
    for name in compose_files:
        content = quiet(remote.read_small, posixpath.join(folder, name), COMPOSE_MAX_BYTES)
        if not content:
            continue
        for path in env_files_in(content.decode("utf-8", errors="replace")):
            found.append(path if path.startswith("/") else posixpath.normpath(posixpath.join(folder, path)))
    folder_env = posixpath.join(folder, ".env")
    if quiet(remote.exists, folder_env, default=False):
        found.append(folder_env)
    return list(dict.fromkeys(found))


def env_files_in(text: str) -> list[str]:
    lines = text.splitlines()
    found: list[str] = []
    for index, line in enumerate(lines):
        matched = ENV_FILE_LINE.match(line)
        if matched is None:
            continue
        rest = matched.group(2).split(" #", 1)[0].strip()
        if rest:
            found += [_unquoted(item) for item in rest.strip("[]").split(",")]
            continue
        indent = len(matched.group(1))
        for following in lines[index + 1 :]:
            if not following.strip():
                continue
            item = LIST_ITEM.match(following)
            if item is None or len(item.group(1)) < indent:
                if not following.startswith(" " * (indent + 1)):
                    break
                stripped = following.strip()
                if stripped.startswith("path:"):
                    found.append(_unquoted(stripped[len("path:"):]))
                continue
            value = item.group(2).strip()
            if value.startswith("path:"):
                value = value[len("path:"):]
            elif ":" in value and not value.startswith(("/", ".", "~")):
                continue
            found.append(_unquoted(value))
    return [path for path in found if path]


def _unquoted(value: str) -> str:
    return value.strip().strip("'\"").strip()


def matched_containers(
    remote: RemoteHost,
    engine: str,
    folder: str,
    listed: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    containers = listed if listed is not None else listed_containers(remote, engine)
    matched = [
        container
        for container in containers
        if well_named(container) and belongs(container, folder)
    ]
    return replicas_joined(matched)


def listed_containers(
    remote: RemoteHost, engine: str, unread: list[dict[str, str]] | None = None
) -> list[dict[str, Any]]:
    listed = quiet(remote.run, [engine, "ps", "--all", "--no-trunc", "--format", "{{.ID}}"])
    if listed is None or not listed.ok:
        return []
    ids = [
        identifier for identifier in listed.stdout.split() if CONTAINER_ID.match(identifier)
    ][:CONTAINERS_INSPECTED]
    left_out: list[str] = []
    rows = inspected_rows(remote, engine, ids, left_out)
    if unread is not None:
        unread.extend({"engine": engine, "id": identifier} for identifier in left_out)
    return [summary(engine, row) for row in rows if isinstance(row, dict)]


def inspected_rows(
    remote: RemoteHost, engine: str, ids: list[str], left_out: list[str]
) -> list[Any]:
    if not ids:
        return []
    inspected = quiet(
        remote.run,
        [engine, "inspect", "--type", "container", "--format", INSPECTED_FIELDS, *ids],
    )
    if inspected is None:
        return []
    if not inspected.stdout_truncated:
        return json_rows(inspected.stdout)
    if len(ids) == 1:
        left_out.extend(ids)
        return []
    half = len(ids) // 2
    return inspected_rows(remote, engine, ids[:half], left_out) + inspected_rows(
        remote, engine, ids[half:], left_out
    )


def json_rows(text: str) -> list[Any]:
    text = text.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        return [parsed]
    rows = []
    for line in text.splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def well_named(container: dict[str, Any]) -> bool:
    names = [container["compose_project"], container["compose_service"]]
    return (
        bool(CONTAINER_NAME.regex.match(container["name"]))
        and all(COMPOSE_NAME.regex.match(name) for name in names if name)
        and all(COMPOSE_FILE.regex.match(path) for path in container["compose_files"])
        and (not container["workdir"] or container["workdir"].startswith("/"))
    )


def summary(engine: str, row: dict[str, Any]) -> dict[str, Any]:
    config = row.get("Config") if isinstance(row.get("Config"), dict) else {}
    labels = config.get("Labels") if isinstance(config.get("Labels"), dict) else {}
    state = row.get("State") if isinstance(row.get("State"), dict) else {}
    name = str(row.get("Name") or "").lstrip("/")
    environment = [item for item in config.get("Env") or [] if isinstance(item, str)]
    settings = next(
        (item.split("=", 1)[1] for item in environment if item.startswith("DJANGO_SETTINGS_MODULE=")),
        "",
    )
    path_dirs = next(
        (item.split("=", 1)[1] for item in environment if item.startswith("PATH=")), ""
    )
    compose_dir = _label(labels, "project.working_dir")
    config_files = [
        path.strip()
        for path in _label(labels, "project.config_files").split(",")
        if path.strip()
    ]
    return {
        "engine": engine,
        "name": name,
        "running": bool(state.get("Running")),
        "image": str(config.get("Image") or ""),
        "image_id": str(row.get("Image") or ""),
        "compose_project": _label(labels, "project"),
        "compose_service": _label(labels, "service"),
        "compose_dir": compose_dir,
        "compose_files": [
            posixpath.relpath(path, compose_dir) if compose_dir and path.startswith(compose_dir + "/") else path
            for path in config_files
        ],
        "workdir": str(config.get("WorkingDir") or ""),
        "settings_module": settings if SETTINGS_PATTERN.match(settings) else "",
        "pythons": [
            posixpath.join(folder, "python")
            for folder in path_dirs.split(":")
            if folder.startswith("/") and "venv" in folder
        ],
        "mounts": [
            {
                "type": str(mount.get("Type") or ""),
                "source": str(mount.get("Source") or ""),
                "destination": str(mount.get("Destination") or ""),
                "rw": bool(mount.get("RW", True)),
            }
            for mount in row.get("Mounts") or []
            if isinstance(mount, dict) and mount.get("Destination")
        ],
        "replicas": 1,
    }


SETTINGS_PATTERN = re.compile(r"^[A-Za-z_][\w.]*$")


def _label(labels: dict[str, Any], name: str) -> str:
    value = labels.get(COMPOSE_LABEL + name) or labels.get(PODMAN_COMPOSE_LABEL + name)
    return str(value) if value else ""


def belongs(container: dict[str, Any], folder: str) -> bool:
    if container["compose_dir"] and _inside(container["compose_dir"], folder):
        return True
    return any(
        mount["source"] and mount["type"] in ("bind", "") and _inside(mount["source"], folder)
        for mount in container["mounts"]
    )


def _inside(path: str, folder: str) -> bool:
    path, folder = path.rstrip("/") or "/", folder.rstrip("/") or "/"
    return path == folder or path.startswith(folder + "/")


def replicas_joined(containers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    joined: dict[tuple, dict[str, Any]] = {}
    for container in sorted(containers, key=lambda found: (not found["running"], found["name"])):
        key = (
            (container["engine"], container["compose_project"], container["compose_service"])
            if container["compose_service"]
            else (container["engine"], container["name"])
        )
        if key in joined:
            joined[key]["replicas"] += 1
            continue
        joined[key] = dict(container)
    return list(joined.values())


def find_project(remote: RemoteHost, profile: DbsProfile, folders: list[str]) -> dict[str, Any] | None:
    starts = [folder for folder in dict.fromkeys(folders) if folder]
    result = quiet(
        lambda: remote.run_python(
            profile, ["-c", FIND_PROJECT, *starts], with_settings=False
        )
    )
    if result is None or not result.ok:
        return None
    found = _json_object(result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "")
    return found if found and found.get("manage") else None


def _json_object(text: str) -> dict[str, Any] | None:
    try:
        found = json.loads(text.strip() or "null")
    except ValueError:
        return None
    return found if isinstance(found, dict) else None


def project_folders(remote: RemoteHost, home: str) -> list[str]:
    found: list[str] = []
    composes: list[str] = []
    for root in SEARCH_ROOTS:
        start = home if root == "~" else root
        if start:
            _search(remote, start, SEARCH_DEPTH, found, composes)
    return list(dict.fromkeys([*composes, *found]))


def _search(
    remote: RemoteHost,
    folder: str,
    depth: int,
    found: list[str],
    composes: list[str],
) -> None:
    entries = quiet(remote.listdir, folder, default=[]) or []
    names = {entry.name: entry for entry in entries[:ENTRIES_PER_FOLDER]}
    manage = names.get(MANAGE)
    if manage is not None and manage.kind == EntryKind.FILE:
        found.append(folder)
    if any(
        names[name].kind == EntryKind.FILE for name in COMPOSE_FILES if name in names
    ):
        composes.append(folder)
    if depth == 0:
        return
    for name in sorted(names):
        entry = names[name]
        if entry.kind == EntryKind.FOLDER and not name.startswith("."):
            _search(remote, posixpath.join(folder, name), depth - 1, found, composes)


def settings_module(remote: RemoteHost, project: str) -> str:
    content = quiet(
        remote.read_small, posixpath.join(project, MANAGE), MANAGE_MAX_BYTES
    )
    if not content:
        return ""
    match = SETTINGS_MODULE.search(content.decode("utf-8", errors="replace"))
    return match.group(1) if match else ""
