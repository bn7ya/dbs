from __future__ import annotations

import json
import posixpath
import re
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from dbs.manager.servers.gateways import DbsProfile, EntryKind, RemoteHost
from dbs.manager.servers.services.pythons import quiet

FACTS_MARKER = "DBS-FACTS "
TEXT_LIMIT = 255
DATABASE_FACTS = """
import json
from urllib.parse import urlsplit
from django.conf import settings
from django.db import connections

def place(url):
    if not isinstance(url, str) or "://" not in url:
        return None
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    return {"scheme": parts.scheme, "host": parts.hostname or "", "port": port}

default = settings.DATABASES.get("default") or {}
caches = []
for cache in (getattr(settings, "CACHES", None) or {}).values():
    location = cache.get("LOCATION")
    for item in location if isinstance(location, (list, tuple)) else [location]:
        found = place(item)
        if found:
            caches.append(found)
broker = getattr(settings, "CELERY_BROKER_URL", None) or getattr(settings, "BROKER_URL", None)
print("DBS-FACTS " + json.dumps({
    "vendor": connections["default"].vendor if default else "",
    "engine": str(default.get("ENGINE") or ""),
    "host": str(default.get("HOST") or ""),
    "port": str(default.get("PORT") or ""),
    "name": str(default.get("NAME") or ""),
    "user": str(default.get("USER") or ""),
    "caches": caches,
    "broker": place(broker),
}))
"""
DATABASE_KEYS = ("vendor", "engine", "host", "port", "name", "user")
PLACE_KEYS = ("scheme", "host")
VENDORS = {"postgresql": "postgresql", "mysql": "mysql", "sqlite": "sqlite"}
LOCAL_HOSTS = frozenset({"", "localhost", "127.0.0.1", "::1"})
HOST_GATEWAYS = frozenset(
    {"host.docker.internal", "host.containers.internal", "172.17.0.1", "10.88.0.1"}
)
GIT_ENV = {"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}
COMMIT = re.compile(r"^[0-9a-f]{40,64}$")
BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
UNIT_FOLDERS = (("/etc/systemd/system", "system"),)
USER_UNIT_FOLDER = ".config/systemd/user"
UNIT_SUFFIXES = (".service", ".socket", ".timer")
SUPERVISOR_FOLDERS = ("/etc/supervisor/conf.d", "/etc/supervisord.d")
SITE_FOLDERS = (
    "/etc/nginx/sites-enabled",
    "/etc/nginx/sites-available",
    "/etc/nginx/conf.d",
)
ENABLED_SITES = "/etc/nginx/sites-enabled"
SERVICE_FILES_READ = 200
SERVICE_FILE_BYTES = 64 * 1024
SERVICES_LINE = re.compile(r"^services:\s*$")
KEY_LINE = re.compile(r"^(\s+)([A-Za-z0-9][A-Za-z0-9_.-]*):\s*(.*)$")
PLACEMENT_ANSWERS = {
    "file": "file",
    "host_package": "this_server",
    "compose_service": "compose",
    "companion_container": "this_server",
    "remote": "elsewhere",
}


def database_facts(remote: RemoteHost, profile: DbsProfile) -> dict[str, Any] | None:
    result = quiet(remote.run_manage, profile, ["shell", "-c", DATABASE_FACTS])
    if result is None or not result.ok:
        return None
    return parsed_database_facts(result.stdout)


def parsed_database_facts(stdout: str) -> dict[str, Any] | None:
    line = next(
        (
            line[len(FACTS_MARKER) :]
            for line in reversed(stdout.splitlines())
            if line.startswith(FACTS_MARKER)
        ),
        None,
    )
    if line is None:
        return None
    try:
        found = json.loads(line)
    except ValueError:
        return None
    if not isinstance(found, dict):
        return None
    facts: dict[str, Any] = {key: _text(found.get(key)) for key in DATABASE_KEYS}
    facts["caches"] = [
        place for place in map(_place, _items(found.get("caches"))) if place
    ][:10]
    facts["broker"] = _place(found.get("broker"))
    return facts


def _text(value: Any) -> str:
    return value[:TEXT_LIMIT] if isinstance(value, str) else ""


def _items(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _place(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    port = value.get("port")
    return {
        **{key: _text(value.get(key)) for key in PLACE_KEYS},
        "port": port if isinstance(port, int) and 0 < port < 65536 else None,
    }


def strip_credentials(url: str) -> tuple[str, bool]:
    if "://" not in url:
        return url, False
    try:
        parts = urlsplit(url)
    except ValueError:
        return "", True
    if "@" not in parts.netloc:
        return url, False
    userinfo, _, host = parts.netloc.rpartition("@")
    keep_user = parts.scheme == "ssh" and ":" not in userinfo
    netloc = f"{userinfo}@{host}" if keep_user else host
    stripped = keep_user and netloc == parts.netloc
    return urlunsplit(parts._replace(netloc=netloc)), not stripped


def git_facts(remote: RemoteHost, folder: str) -> dict[str, Any] | None:
    if not folder:
        return None
    head = _git(remote, folder, "rev-parse", "HEAD")
    if head is None or not COMMIT.match(head):
        return None
    branch = _git(remote, folder, "rev-parse", "--abbrev-ref", "HEAD") or ""
    origin, had_credentials = strip_credentials(
        _git(remote, folder, "remote", "get-url", "origin") or ""
    )
    status = quiet(
        lambda: remote.run(["git", "-C", folder, "status", "--porcelain"], env=GIT_ENV)
    )
    dirty = (
        len([line for line in status.stdout.splitlines() if line.strip()])
        if status is not None and status.ok
        else None
    )
    return {
        "head": head,
        "branch": branch if BRANCH.match(branch) else "",
        "remote": origin[:TEXT_LIMIT * 2],
        "remote_has_credentials": had_credentials,
        "dirty": dirty,
    }


def _git(remote: RemoteHost, folder: str, *arguments: str) -> str | None:
    result = quiet(lambda: remote.run(["git", "-C", folder, *arguments], env=GIT_ENV))
    if result is None or not result.ok:
        return None
    lines = result.stdout.strip().splitlines()
    return lines[-1].strip() if lines else None


def services_of(compose_text: str) -> dict[str, dict[str, Any]]:
    services: dict[str, dict[str, Any]] = {}
    inside = False
    service_indent: int | None = None
    current: str | None = None
    for line in compose_text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith((" ", "\t")):
            inside = bool(SERVICES_LINE.match(line))
            current = None
            service_indent = None
            continue
        if not inside:
            continue
        matched = KEY_LINE.match(line)
        if matched is None:
            continue
        indent = len(matched.group(1))
        if service_indent is None or indent <= service_indent:
            service_indent = indent
            current = matched.group(2)
            services[current] = {"build": False, "image": ""}
        elif current is not None and matched.group(2) == "build":
            services[current]["build"] = True
        elif current is not None and matched.group(2) == "image":
            services[current]["image"] = matched.group(3).strip().strip("'\"")[:TEXT_LIMIT]
    return services


def host_services(remote: RemoteHost, home: str) -> list[dict[str, Any]]:
    folders = [
        *((folder, "unit", scope) for folder, scope in UNIT_FOLDERS),
        (posixpath.join(home, USER_UNIT_FOLDER), "unit", "user"),
        *((folder, "supervisor", "system") for folder in SUPERVISOR_FOLDERS),
        *((folder, "site", "system") for folder in SITE_FOLDERS),
    ]
    enabled = {
        entry.name
        for entry in quiet(remote.listdir, ENABLED_SITES, default=[]) or []
    }
    found: list[dict[str, Any]] = []
    budget = SERVICE_FILES_READ
    for folder, kind, scope in folders:
        entries = quiet(remote.listdir, folder, default=[]) or []
        for entry in sorted(entries, key=lambda item: item.name):
            if budget <= 0:
                return found
            if entry.kind not in (EntryKind.FILE, EntryKind.LINK):
                continue
            if kind == "unit" and not entry.name.endswith(UNIT_SUFFIXES):
                continue
            path = posixpath.join(folder, entry.name)
            budget -= 1
            content = quiet(remote.read_small, path, SERVICE_FILE_BYTES)
            if content is None:
                continue
            found.append(
                {
                    "kind": kind,
                    "scope": scope,
                    "name": entry.name,
                    "path": path,
                    "enabled": kind != "site" or entry.name in enabled,
                    "text": content.decode("utf-8", errors="replace"),
                }
            )
    return found


def services_for(
    services: Iterable[Mapping[str, Any]], folder: str
) -> list[dict[str, Any]]:
    if not folder or folder == "/":
        return []
    seen: set[tuple[str, str]] = set()
    kept = []
    for service in services:
        if not mentions(service["text"], folder):
            continue
        key = (service["kind"], service["name"])
        if key in seen:
            continue
        seen.add(key)
        kept.append({k: v for k, v in service.items() if k != "text"})
    return kept


def mentions(text: str, folder: str) -> bool:
    folder = folder.rstrip("/")
    return re.search(re.escape(folder) + r"(?=[/\s;\"'=:]|$)", text, re.M) is not None


def placement(
    database: Mapping[str, Any] | None,
    services: Iterable[str] = (),
    containers: Iterable[str] = (),
) -> str:
    if not database or not database.get("vendor"):
        return ""
    if database["vendor"] == "sqlite":
        return "file"
    host = str(database.get("host") or "")
    if host in LOCAL_HOSTS or host.startswith("/") or host in HOST_GATEWAYS:
        return "host_package"
    if host in set(services):
        return "compose_service"
    if host in set(containers):
        return "companion_container"
    return "remote"


def compose_services(
    remote: RemoteHost, folder: str, compose_files: Iterable[str], limit: int
) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for name in compose_files:
        path = name if name.startswith("/") else posixpath.join(folder, name)
        content = quiet(remote.read_small, path, limit)
        if content:
            found.update(services_of(content.decode("utf-8", errors="replace")))
    return found


def facts_for(
    remote: RemoteHost,
    candidate: Mapping[str, Any],
    *,
    database: Mapping[str, Any] | None,
    services_found: Iterable[Mapping[str, Any]],
    project_services: Iterable[str] = (),
    containers: Iterable[str] = (),
    image: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    folder = str(candidate.get("project_dir") or "")
    facts: dict[str, Any] = {
        "database": dict(database) if database else None,
        "placement": placement(database, project_services, containers),
        "git": git_facts(remote, folder),
        "image": dict(image) if image else None,
        "services": services_for(services_found, folder),
        "env_source": env_source(candidate),
        "folder_read": bool(folder),
    }
    facts["detected"] = detected_profile(candidate, facts)
    return facts


def env_source(candidate: Mapping[str, Any]) -> str:
    entries = candidate.get("env") or []
    sources = {entry.get("source") for entry in entries}
    if "compose" in sources:
        return "compose_env_file"
    if any(
        entry.get("source") == "dbs" and entry.get("location") == "container"
        for entry in entries
    ):
        return "image"
    if entries:
        return "folder_env"
    return "environment" if candidate.get("kind") != "host" else ""


def detected_profile(
    candidate: Mapping[str, Any], facts: Mapping[str, Any]
) -> dict[str, str]:
    database = facts.get("database") or {}
    git = facts.get("git")
    services = facts.get("services") or []
    kinds = {(service["kind"], service["scope"]) for service in services}
    profile = {
        "runs_in": str(candidate.get("kind") or ""),
        "engine": str(candidate.get("engine") or ""),
        "database": VENDORS.get(database.get("vendor", ""), "other")
        if database.get("vendor")
        else "",
        "database_runs": PLACEMENT_ANSWERS.get(facts.get("placement") or "", ""),
        "settings_from": env_source(candidate),
        "source": "git"
        if git
        else ("copied" if candidate.get("kind") == "host" and facts.get("folder_read") else ""),
        "process_manager": "systemd_user"
        if ("unit", "user") in kinds
        else "systemd"
        if ("unit", "system") in kinds
        else "supervisor"
        if any(kind == "supervisor" for kind, _ in kinds)
        else "",
        "web_server": "nginx" if any(kind == "site" for kind, _ in kinds) else "",
    }
    return {key: value for key, value in profile.items() if value}
