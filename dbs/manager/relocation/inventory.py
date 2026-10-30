from __future__ import annotations

import posixpath
import re
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from dbs.manager.applications.models import Application
from dbs.manager.applications.repositories import ApplicationRepository
from dbs.manager.applications.services import facts as found_facts
from dbs.manager.applications.services.discovery_service import (
    COMPOSE_LABEL,
    PODMAN_COMPOSE_LABEL,
    json_rows,
)
from dbs.manager.conf import data_dir
from dbs.manager.relocation import catalogue, packages
from dbs.manager.relocation.catalogue import Command
from dbs.manager.relocation.database import DB_IDENT, vendor_need
from dbs.manager.relocation.packages import PackagePlan
from dbs.manager.relocation.systems import OS_RELEASE, System, system_of
from dbs.manager.servers.exceptions import RemoteCommandFailed
from dbs.manager.servers.gateways import ENGINES, ContainerTarget, DbsProfile, RemoteHost
from dbs.manager.servers.models import Server
from dbs.manager.servers.services.pythons import quiet
from dbs.manager.servers.services.server_service import engine_report
from dbs.transports import RemoteResult

OS_RELEASE_BYTES = 64 * 1024
COMPOSE_BYTES = 256 * 1024
ENV_BYTES = 256 * 1024
CONTAINERS_INSPECTED = 60
SPACE_MARGIN = 1.1
PYTHON_VERSION = "import sys; print('%d.%d' % sys.version_info[:2])"
ID_LINE = re.compile(r"uid=(\d+)\(([^)]*)\)\s+gid=(\d+)")
USER_LINE = re.compile(r"^\s*(User|Group)\s*=\s*([a-z_][a-z0-9_-]{0,31})\s*$", re.M)
CERTIFICATE_LINE = re.compile(r"^\s*ssl_certificate(?:_key)?\s+([^;\s]+)\s*;", re.M)
SYSTEM_PATHS = ("/var/run", "/run", "/dev", "/proc", "/sys", "/etc/localtime", "/etc/timezone")
DEFAULT_NETWORKS = frozenset({"", "default", "bridge", "host", "none", "podman", "slirp4netns", "pasta"})
DEFAULT_LOG_DRIVERS = frozenset({"", "json-file", "journald", "k8s-file", "local"})
UNSUPPORTED_HOST_CONFIG = (
    ("Privileged", "privileged"),
    ("CapAdd", "cap_add"),
    ("CapDrop", "cap_drop"),
    ("Devices", "devices"),
    ("SecurityOpt", "security_opt"),
    ("Sysctls", "sysctls"),
    ("Tmpfs", "tmpfs"),
    ("ExtraHosts", "extra_hosts"),
    ("Links", "links"),
    ("VolumesFrom", "volumes_from"),
    ("Dns", "dns"),
    ("Ulimits", "ulimits"),
)
DATABASE_SERVICES = frozenset({"compose_service", "companion_container"})
REDIS_SCHEMES = frozenset({"redis", "rediss"})
LOCAL_HOSTS = frozenset({"", "localhost", "127.0.0.1", "::1"})


@dataclass(frozen=True)
class Choice:
    application: Application
    name: str
    folder: str
    skip_volumes: frozenset[str] = frozenset()
    copy_plans: bool = True


@dataclass
class Side:
    remote: RemoteHost
    server: Server
    mode: str
    system: System | None = None
    uid: str = ""
    gid: str = ""
    user: str = ""
    home: str = "/"
    engines: dict[str, Any] = field(default_factory=dict)
    selinux: str = ""

    def run(self, command: Command) -> RemoteResult | None:
        if command.root and self.mode not in (catalogue.ROOT, catalogue.NOPASSWD):
            return None
        argv = catalogue.privileged(command, self.mode) if command.root else list(command.argv)
        try:
            return self.remote.run(argv, cwd=command.cwd, env=command.environment)
        except RemoteCommandFailed:
            return None

    def output(self, command: Command) -> str:
        result = self.run(command)
        return result.stdout.strip() if result is not None and result.ok else ""

    def describe(self) -> dict[str, Any]:
        return {
            "server": str(self.server.pk),
            "name": self.server.name,
            "system": self.system.describe() if self.system else None,
            "user": {"name": self.user, "uid": self.uid, "gid": self.gid},
            "sudo": self.mode,
            "engines": self.engines,
            "selinux": self.selinux,
            "home": self.home,
        }


def learn(side: Side) -> Side:
    content = quiet(side.remote.read_small, OS_RELEASE, OS_RELEASE_BYTES)
    machine = side.output(catalogue.uname_machine())
    side.system = system_of(
        content.decode("utf-8", errors="replace") if content else "", machine
    )
    found = ID_LINE.search(side.output(catalogue.user_ids()))
    if found:
        side.uid, side.user, side.gid = found.group(1), found.group(2), found.group(3)
    side.home = quiet(side.remote.realpath, ".") or "/"
    side.engines = {engine: engine_report(side.remote, engine) for engine in ENGINES}
    side.selinux = side.output(catalogue.selinux_mode())
    return side


def inside(path: str, folder: str) -> bool:
    path, folder = path.rstrip("/") or "/", folder.rstrip("/") or "/"
    return bool(folder) and (path == folder or path.startswith(folder + "/"))


def mapped(path: str, source_folder: str, target_folder: str) -> str:
    if source_folder and inside(path, source_folder):
        rest = path[len(source_folder.rstrip("/")) :]
        return (target_folder.rstrip("/") + rest) or "/"
    return path


def relative(path: str, folder: str) -> str:
    return posixpath.relpath(path, folder)


def rewritten(text: str, source_folder: str, target_folder: str) -> str:
    if not source_folder or source_folder == target_folder:
        return text
    pattern = re.escape(source_folder.rstrip("/")) + r"(?=[/\s;\"'=:]|$)"
    return re.sub(pattern, target_folder.rstrip("/"), text, flags=re.M)


def size_of(side: Side, path: str, excludes: Iterable[str] = ()) -> int | None:
    result = side.run(catalogue.disk_usage(path, excludes))
    if (result is None or not result.ok) and side.mode in (catalogue.ROOT, catalogue.NOPASSWD):
        result = side.run(catalogue.disk_usage(path, excludes, root=True))
    if result is None or not result.stdout.strip():
        return None
    head = result.stdout.strip().split()[0]
    return int(head) if head.isdigit() else None


def unreadable(side: Side, path: str) -> bool:
    result = side.run(catalogue.unreadable(path))
    return result is None or bool(result.stdout.strip()) or not result.ok


def inspected(side: Side, engine: str) -> list[dict[str, Any]]:
    if not side.engines.get(engine, {}).get("usable"):
        return []
    listed = side.run(Command((engine, "ps", "--all", "--no-trunc", "--format", "{{json .}}")))
    if listed is None or not listed.ok:
        return []
    ids = [
        identifier
        for identifier in (_identifier(row) for row in json_rows(listed.stdout))
        if identifier and catalogue.CONTAINER.match(identifier)
    ][:CONTAINERS_INSPECTED]
    if not ids:
        return []
    rows = side.run(Command((engine, "inspect", "--type", "container", *ids)))
    if rows is None or not rows.ok:
        return []
    return [row for row in json_rows(rows.stdout) if isinstance(row, dict)]


def _identifier(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    for key in ("ID", "Id", "id"):
        if isinstance(row.get(key), str):
            return row[key]
    return ""


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def name_of(row: Mapping[str, Any]) -> str:
    return str(row.get("Name") or "").lstrip("/")


def label(row: Mapping[str, Any], name: str) -> str:
    labels = _dict(_dict(row.get("Config")).get("Labels"))
    return str(labels.get(COMPOSE_LABEL + name) or labels.get(PODMAN_COMPOSE_LABEL + name) or "")


def mounts_of(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "type": str(mount.get("Type") or ""),
            "name": str(mount.get("Name") or ""),
            "source": str(mount.get("Source") or ""),
            "destination": str(mount.get("Destination") or ""),
            "rw": bool(mount.get("RW", True)),
        }
        for mount in _list(row.get("Mounts"))
        if isinstance(mount, dict) and mount.get("Destination")
    ]


def ports_of(row: Mapping[str, Any]) -> list[catalogue.Port]:
    bindings = _dict(_dict(row.get("HostConfig")).get("PortBindings"))
    found = []
    for key, hosts in bindings.items():
        number, _, protocol = str(key).partition("/")
        for host in _list(hosts):
            port = str(_dict(host).get("HostPort") or "")
            if number.isdigit() and port.isdigit():
                found.append(
                    catalogue.Port(
                        str(_dict(host).get("HostIp") or ""),
                        int(port),
                        int(number),
                        protocol or "tcp",
                    )
                )
    return found


def unsupported_options(row: Mapping[str, Any]) -> list[str]:
    host = _dict(row.get("HostConfig"))
    found = [name for key, name in UNSUPPORTED_HOST_CONFIG if host.get(key)]
    if str(host.get("PidMode") or "") not in ("", "private"):
        found.append("pid_mode")
    if str(host.get("IpcMode") or "") not in ("", "private", "shareable"):
        found.append("ipc_mode")
    if str(_dict(host.get("LogConfig")).get("Type") or "") not in DEFAULT_LOG_DRIVERS:
        found.append("log_driver")
    network = str(host.get("NetworkMode") or "")
    if network.startswith("container:"):
        found.append("network_mode")
    if any("\n" in str(item) for item in _list(_dict(row.get("Config")).get("Env"))):
        found.append("env_newline")
    return found


def networks_of(row: Mapping[str, Any]) -> list[str]:
    mode = str(_dict(row.get("HostConfig")).get("NetworkMode") or "")
    names = list(_dict(_dict(row.get("NetworkSettings")).get("Networks")))
    return [
        name
        for name in dict.fromkeys([mode, *names])
        if name not in DEFAULT_NETWORKS and catalogue.NETWORK.match(name)
    ]


def spec_of(
    engine: str,
    row: Mapping[str, Any],
    image_config: Mapping[str, Any],
    *,
    env_file: str = "",
) -> catalogue.ContainerSpec:
    config = _dict(row.get("Config"))
    host = _dict(row.get("HostConfig"))
    restart = _dict(host.get("RestartPolicy"))
    networks = networks_of(row)
    mode = str(host.get("NetworkMode") or "")
    labels = {
        str(key): str(value)
        for key, value in _dict(config.get("Labels")).items()
        if key not in _dict(image_config.get("Labels"))
        and not str(key).startswith((COMPOSE_LABEL, PODMAN_COMPOSE_LABEL))
    }
    entrypoint = config.get("Entrypoint")
    command = config.get("Cmd")
    return catalogue.ContainerSpec(
        engine=engine,
        name=name_of(row),
        image=str(config.get("Image") or ""),
        env_file=env_file,
        ports=tuple(ports_of(row)),
        mounts=tuple(
            catalogue.Mount(
                mount["type"],
                mount["name"] if mount["type"] == "volume" else mount["source"],
                mount["destination"],
                not mount["rw"],
            )
            for mount in mounts_of(row)
            if mount["type"] in ("bind", "volume")
        ),
        restart=str(restart.get("Name") or "no"),
        restart_retries=int(restart.get("MaximumRetryCount") or 0),
        network=networks[0] if networks else ("host" if mode == "host" else ""),
        user=str(config.get("User") or "")
        if config.get("User") != image_config.get("User")
        else "",
        workdir=str(config.get("WorkingDir") or "")
        if config.get("WorkingDir") != image_config.get("WorkingDir")
        else "",
        entrypoint=tuple(entrypoint)
        if isinstance(entrypoint, list) and entrypoint != image_config.get("Entrypoint")
        else None,
        command=tuple(command)
        if isinstance(command, list) and command != image_config.get("Cmd")
        else None,
        labels=tuple(sorted(labels.items())),
    )


def env_lines(row: Mapping[str, Any], image_config: Mapping[str, Any]) -> list[str]:
    inherited = set(_list(image_config.get("Env")))
    return [
        item
        for item in _list(_dict(row.get("Config")).get("Env"))
        if isinstance(item, str) and item not in inherited and "=" in item
    ]


def image_config(side: Side, engine: str, ref: str) -> dict[str, Any]:
    result = side.run(Command((engine, "image", "inspect", catalogue.matched(catalogue.IMAGE_REF, ref, "image"))))
    rows = json_rows(result.stdout) if result is not None and result.ok else []
    return _dict(_dict(rows[0]).get("Config")) if rows else {}


def image_facts(side: Side, engine: str, ref: str) -> dict[str, Any] | None:
    result = side.run(catalogue.image_facts(engine, ref))
    if result is None or not result.ok:
        return None
    parts = result.stdout.strip().split()
    if len(parts) < 2:
        return None
    return {
        "id": parts[0],
        "bytes": int(parts[1]) if parts[1].isdigit() else None,
        "architecture": packages_architecture(parts[2] if len(parts) > 2 else ""),
    }


def packages_architecture(value: str) -> str:
    return {"x86_64": "amd64", "aarch64": "arm64"}.get(value, value)


def volume_exists(side: Side, engine: str, volume: str) -> bool:
    if not side.engines.get(engine, {}).get("usable"):
        return False
    result = side.run(catalogue.volume_mountpoint(engine, volume))
    return result is not None and result.ok


def existing_ancestor(remote: RemoteHost, path: str) -> str:
    current = path
    while current not in ("", "/"):
        if quiet(remote.exists, current, default=False):
            return current
        current = posixpath.dirname(current)
    return "/"


def holds_anything(remote: RemoteHost, path: str) -> bool:
    entries = quiet(remote.listdir, path, default=None)
    if entries is None:
        return quiet(remote.exists, path, default=False) or False
    return bool(entries)


def free_space(side: Side, paths: Iterable[str]) -> dict[str, dict[str, Any]]:
    ancestors = sorted({existing_ancestor(side.remote, path) for path in paths})
    if not ancestors:
        return {}
    result = side.run(catalogue.free_space(ancestors))
    if result is None or not result.stdout.strip():
        return {}
    lines = result.stdout.strip().splitlines()[1:]
    filesystems = {}
    for ancestor, line in zip(ancestors, lines):
        parts = line.split()
        if len(parts) >= 6 and parts[3].isdigit():
            filesystems[ancestor] = {"filesystem": parts[5], "available": int(parts[3])}
    return filesystems


def listening_ports(side: Side) -> set[int]:
    found = set()
    for line in side.output(catalogue.listening()).splitlines():
        parts = line.split()
        if len(parts) >= 4:
            port = parts[3].rsplit(":", 1)[-1]
            if port.isdigit():
                found.add(int(port))
    return found


def python_version(side: Side, python: str, cwd: str | None = None) -> str:
    return side.output(Command((python, "-c", PYTHON_VERSION), cwd=cwd))


def certificate_paths(text: str) -> list[str]:
    return [path for path in CERTIFICATE_LINE.findall(text) if path.startswith("/")]


def unit_users(text: str) -> list[str]:
    return [name for _, name in USER_LINE.findall(text) if name != "root"]


def user_exists(side: Side, name: str) -> bool:
    result = side.run(Command(("id", "-u", catalogue.matched(catalogue.USER, name, "user"))))
    return result is not None and result.ok


def note(plan: dict[str, Any], code: str, **facts: Any) -> None:
    plan["notes"].append({"code": code, **facts})


def block(plan: dict[str, Any], code: str, **facts: Any) -> None:
    plan["blockers"].append({"code": code, **facts})


class Survey:
    def __init__(self, source: Side, target: Side, connections: Any) -> None:
        self.source = source
        self.target = target
        self.connections = connections
        self.applications = ApplicationRepository()
        self.source_services: list[dict[str, Any]] | None = None
        self.source_rows: dict[str, list[dict[str, Any]]] = {}

    def rows(self, engine: str) -> list[dict[str, Any]]:
        if engine not in self.source_rows:
            self.source_rows[engine] = inspected(self.source, engine)
        return self.source_rows[engine]

    def services(self) -> list[dict[str, Any]]:
        if self.source_services is None:
            self.source_services = found_facts.host_services(self.source.remote, self.source.home)
        return self.source_services

    def collect(self, choices: list[Choice]) -> dict[str, Any]:
        plans = [self.application(choice) for choice in choices]
        needs: set[str] = set()
        for plan in plans:
            needs.update(plan["needs"])
        package_plan = self.package_plan(needs, plans)
        inventory: dict[str, Any] = {
            "source": self.source.describe(),
            "target": self.target.describe(),
            "packages": package_plan.describe(),
            "needs": sorted(needs),
            "applications": plans,
            "blockers": [],
            "notes": [],
        }
        self.server_checks(inventory, plans, package_plan)
        inventory["needs_sudo"] = {
            "target": bool(package_plan.packages or package_plan.repositories)
            or any(plan["needs_root"] for plan in plans),
            "source": any(plan["source_root"] for plan in plans),
        }
        inventory["totals"] = totals(plans)
        largest = inventory["totals"]["largest"]
        free = shutil.disk_usage(_existing(data_dir())).free
        inventory["totals"]["manager_free"] = free
        if largest and free < largest * SPACE_MARGIN:
            block(inventory, "manager_space_low", needed=largest, available=free)
        return inventory

    def package_plan(self, needs: set[str], plans: list[dict[str, Any]]) -> PackagePlan:
        system = self.target.system
        if system is None or not system.supported:
            return packages.resolve(system or system_of("", ""), needs, ())
        python = next(
            (plan["python"]["version"] for plan in plans if plan.get("python", {}).get("version")),
            "",
        )
        asked = packages.asked_packages(system, needs, python=python)
        installed = self.installed(system, asked)
        return packages.resolve(system, needs, installed, python=python)

    def installed(self, system: System, asked: list[str]) -> list[str]:
        if not asked:
            return []
        if system.family == "debian":
            result = self.target.run(catalogue.dpkg_installed(asked))
            stdout = result.stdout if result is not None else ""
            missing = packages.missing_from_dpkg(stdout, asked)
        else:
            result = self.target.run(catalogue.rpm_installed(asked))
            stdout = result.stdout if result is not None else ""
            missing = packages.missing_from_rpm(stdout, asked)
        return [name for name in asked if name not in missing]

    def server_checks(
        self,
        inventory: dict[str, Any],
        plans: list[dict[str, Any]],
        package_plan: PackagePlan,
    ) -> None:
        target = self.target
        for code in package_plan.blockers:
            block(inventory, code)
        for code in package_plan.notes:
            note(inventory, code)
        if target.system is not None and not target.system.supported and "os_unsupported" not in package_plan.blockers:
            block(inventory, "os_unsupported")
        if target.mode == catalogue.MISSING and inventory["needs"]:
            block(inventory, "sudo_missing")
        if self.source.server.host_key and self.source.server.host_key == target.server.host_key:
            note(inventory, "same_machine")
        if target.selinux.lower() == "enforcing":
            note(inventory, "selinux_enforcing")
        firewall = target.output(catalogue.firewall_active())
        if firewall == "active":
            note(inventory, "firewall_may_block")
        source_arch = self.source.system.architecture if self.source.system else ""
        target_arch = target.system.architecture if target.system else ""
        if source_arch and target_arch and source_arch != target_arch:
            for plan in plans:
                if plan["images"]:
                    block(plan, "architecture_mismatch", source=source_arch, target=target_arch)
        ports = listening_ports(target)
        if self.source.server.host_key != target.server.host_key:
            for plan in plans:
                busy = sorted(set(plan["ports"]) & ports)
                if busy:
                    block(plan, "port_in_use", ports=busy)
        self.space(inventory, plans)
        names = [plan["target_name"] for plan in plans]
        for plan in plans:
            if names.count(plan["target_name"]) > 1:
                block(plan, "name_taken", name=plan["target_name"])

    def space(self, inventory: dict[str, Any], plans: list[dict[str, Any]]) -> None:
        wanted: dict[str, int] = {}
        for plan in plans:
            for target_path, size in placed_sizes(plan):
                wanted[target_path] = wanted.get(target_path, 0) + size
            store = self.engine_store(plan["engine"])
            for item in [*plan["images"], *plan["volumes"]]:
                if item.get("selected", True) and item.get("bytes") and not item.get("on_target"):
                    wanted[store] = wanted.get(store, 0) + 2 * item["bytes"]
        staging = posixpath.join(self.target.home, ".dbs-staging")
        largest = max((size for size in item_sizes(plans)), default=0)
        wanted[staging] = wanted.get(staging, 0) + largest
        free = free_space(self.target, wanted)
        needed: dict[str, int] = {}
        available: dict[str, int] = {}
        for path, size in wanted.items():
            ancestor = existing_ancestor(self.target.remote, path)
            facts = free.get(ancestor)
            if facts is None:
                continue
            needed[facts["filesystem"]] = needed.get(facts["filesystem"], 0) + size
            available[facts["filesystem"]] = facts["available"]
        for filesystem, size in needed.items():
            if size * SPACE_MARGIN > available[filesystem]:
                block(
                    inventory,
                    "not_enough_space",
                    filesystem=filesystem,
                    needed=int(size * SPACE_MARGIN),
                    available=available[filesystem],
                )

    def engine_store(self, engine: str) -> str:
        if engine == "podman" and self.target.uid != "0":
            return posixpath.join(self.target.home, ".local/share/containers")
        return "/var/lib"

    def application(self, choice: Choice) -> dict[str, Any]:
        application = choice.application
        folder = application.project_dir
        target_folder = choice.folder or folder
        plan: dict[str, Any] = {
            "application": str(application.pk),
            "name": application.name,
            "target_name": choice.name,
            "kind": application.kind,
            "engine": application.engine,
            "copy_plans": choice.copy_plans,
            "folder": {"path": folder, "target": target_folder, "bytes": None, "excluded": [], "unreadable": False},
            "extras": [],
            "git": None,
            "env": {"path": application.env_path, "location": application.env_location, "carried": ""},
            "images": [],
            "volumes": [],
            "binds": [],
            "containers": [],
            "networks": [],
            "services": [],
            "ports": [],
            "database": {},
            "units": [],
            "sites": [],
            "users": [],
            "python": {},
            "backup_dir": {},
            "needs": [],
            "needs_root": False,
            "source_root": False,
            "blockers": [],
            "notes": [],
        }
        if not application.has_backup_passphrase:
            block(plan, "passphrase_missing")
        if self.applications.name_in_use(choice.name):
            block(plan, "name_taken", name=choice.name)
        profile = self.connections.dbs_profile(application)
        database = found_facts.database_facts(self.source.remote, profile)
        if application.kind == Application.Kind.HOST:
            self.host(plan, application, database)
        else:
            self.contained(plan, application, choice, database)
        self.folder(plan, application)
        self.backup_dir(plan, application)
        self.env(plan, application)
        if not database:
            note(plan, "facts_unknown")
        return plan

    def database(
        self,
        plan: dict[str, Any],
        database: Mapping[str, Any] | None,
        project_services: Iterable[str],
        containers: Iterable[str],
    ) -> str:
        placement = found_facts.placement(database, project_services, containers)
        action = {
            "remote": "shared",
            "": "unknown",
        }.get(placement, "restore")
        plan["database"] = {
            "vendor": (database or {}).get("vendor", ""),
            "placement": placement,
            "host": (database or {}).get("host", ""),
            "name": (database or {}).get("name", ""),
            "user": (database or {}).get("user", ""),
            "action": action,
        }
        if placement == "remote":
            note(plan, "database_shared_with_source")
        if placement == "host_package":
            need = vendor_need(plan["database"]["vendor"], self.flavour(database))
            if need:
                plan["needs"].append(need)
                plan["needs_root"] = True
                for value in (plan["database"]["name"], plan["database"]["user"]):
                    if not DB_IDENT.match(value or ""):
                        block(plan, "database_name_unsupported", name=value)
            if plan["kind"] != Application.Kind.HOST:
                note(plan, "database_reach_from_container")
        for place in [*(database or {}).get("caches", []), (database or {}).get("broker")]:
            if place and place.get("scheme") in REDIS_SCHEMES and place.get("host") in LOCAL_HOSTS:
                if plan["kind"] == Application.Kind.HOST and "redis" not in plan["needs"]:
                    plan["needs"].append("redis")
                    plan["needs_root"] = True
        broker = (database or {}).get("broker")
        if broker and broker.get("scheme") not in REDIS_SCHEMES:
            note(plan, "broker_queue_not_carried")
        return placement

    def flavour(self, database: Mapping[str, Any] | None) -> str:
        if (database or {}).get("vendor") != "mysql":
            return ""
        version = self.source.output(Command(("mysql", "--version")))
        return "mariadb" if "mariadb" in version.lower() else "mysql"

    def host(self, plan: dict[str, Any], application: Application, database: Mapping[str, Any] | None) -> None:
        folder = application.project_dir
        target_folder = plan["folder"]["target"]
        placement = self.database(plan, database, (), ())
        if placement == "file" and database and database.get("name", "").startswith(folder + "/"):
            plan["folder"]["excluded"].append(relative(database["name"], folder))
        python = application.python_path
        source_version = python_version(self.source, python, folder or None)
        target_version = python_version(self.target, "/usr/bin/python3") or python_version(self.target, "python3")
        venv = python_venv(python)
        same_place = target_folder == folder
        same_system = (
            self.source.system is not None
            and self.target.system is not None
            and self.source.system.architecture == self.target.system.architecture
        )
        carry = bool(venv) and same_place and same_system and source_version == target_version
        plan["python"] = {
            "path": python,
            "version": source_version,
            "target_version": target_version,
            "venv": venv,
            "target_venv": mapped(venv, folder, target_folder) if venv else "",
            "action": "carry" if carry else ("rebuild" if venv else "system"),
        }
        plan["needs"].extend(["python"])
        plan["needs_root"] = True
        if source_version and target_version and source_version != target_version:
            note(plan, "python_version_differs", source=source_version, target=target_version)
        if venv and not carry:
            note(plan, "venv_rebuilt")
            if inside(venv, folder):
                plan["folder"]["excluded"].append(relative(venv, folder))
        services = found_facts.services_for(self.services(), folder)
        for service in services:
            if service["kind"] == "supervisor":
                note(plan, "process_manager_not_carried", path=service["path"])
                continue
            text = self.service_text(service["path"])
            if service["kind"] == "unit":
                target_path = service["path"]
                plan["units"].append(
                    {
                        "name": service["name"],
                        "scope": service["scope"],
                        "path": service["path"],
                        "target_path": target_path,
                    }
                )
                if service["scope"] == "system":
                    plan["needs_root"] = True
                for name in unit_users(text):
                    if not user_exists(self.target, name) and name not in plan["users"]:
                        plan["users"].append(name)
                if holds_anything(self.target.remote, target_path):
                    block(plan, "unit_exists_on_target", path=target_path)
            elif service["kind"] == "site":
                certificates = certificate_paths(text)
                missing = [path for path in certificates if not quiet(self.target.remote.exists, path, default=False)]
                plan["sites"].append(
                    {
                        "name": service["name"],
                        "path": service["path"],
                        "enabled": service["enabled"],
                        "certificates_missing": missing,
                    }
                )
                plan["needs_root"] = True
                if "nginx" not in plan["needs"]:
                    plan["needs"].append("nginx")
                if missing:
                    note(plan, "tls_certificate_missing", site=service["name"])
                if holds_anything(self.target.remote, service["path"]):
                    block(plan, "site_exists_on_target", path=service["path"])
        if plan["users"]:
            plan["needs_root"] = True

    def service_text(self, path: str) -> str:
        content = quiet(self.source.remote.read_small, path, found_facts.SERVICE_FILE_BYTES)
        return content.decode("utf-8", errors="replace") if content else ""

    def contained(
        self,
        plan: dict[str, Any],
        application: Application,
        choice: Choice,
        database: Mapping[str, Any] | None,
    ) -> None:
        engine = application.engine or "docker"
        rows = self.rows(engine)
        if application.kind == Application.Kind.COMPOSE:
            project = application.compose_project
            members = [
                row for row in rows if project and label(row, "project") == project
            ] or [
                row for row in rows if label(row, "service") == application.compose_service
            ]
            declared = found_facts.compose_services(
                self.source.remote, application.project_dir, application.compose_files, COMPOSE_BYTES
            )
            placement = self.database(
                plan,
                database,
                [*declared, *(label(row, "service") for row in members)],
                [name_of(row) for row in rows],
            )
            database_service = plan["database"]["host"] if placement == "compose_service" else ""
            plan["services"] = sorted(
                {
                    label(row, "service")
                    for row in members
                    if _dict(row.get("State")).get("Running") and label(row, "service")
                }
            )
            self.compose_texts(plan, application)
        else:
            app_row = next((row for row in rows if name_of(row) == application.container_name), None)
            placement = self.database(plan, database, (), [name_of(row) for row in rows])
            companions = [plan["database"]["host"]] if placement == "companion_container" else []
            members = [row for row in rows if app_row is not None and row is app_row] + [
                row for row in rows if name_of(row) in companions
            ]
            database_service = plan["database"]["host"] if companions else ""
            if app_row is None:
                block(plan, "container_missing", name=application.container_name)
            for row in members:
                options = unsupported_options(row)
                if options:
                    block(plan, "container_options_unsupported", container=name_of(row), options=options)
                plan["containers"].append(
                    {
                        "name": name_of(row),
                        "companion": row is not app_row,
                        "image": str(_dict(row.get("Config")).get("Image") or ""),
                    }
                )
                if self.target.engines.get(engine, {}).get("usable"):
                    exists = self.target.run(Command((engine, "container", "inspect", "--format", "{{.Name}}", name_of(row))))
                    if exists is not None and exists.ok:
                        block(plan, "container_exists_on_target", name=name_of(row))
                for network in networks_of(row):
                    if network not in plan["networks"]:
                        plan["networks"].append(network)
        self.images(plan, engine, members)
        self.mounts(plan, engine, members, application, choice, database_service)
        plan["ports"] = sorted({port.host_port for row in members for port in ports_of(row)})
        target_engine = self.target.engines.get(engine) or {}
        compose_needed = application.kind == Application.Kind.COMPOSE
        if not target_engine.get("usable") or (compose_needed and not target_engine.get("compose")):
            plan["needs"].append(engine)
            plan["needs_root"] = True
        if database_service and placement == "compose_service":
            plan["database"]["service"] = database_service

    def compose_texts(self, plan: dict[str, Any], application: Application) -> None:
        folder = application.project_dir
        target_folder = plan["folder"]["target"]
        if folder == target_folder:
            return
        for name in application.compose_files:
            path = name if name.startswith("/") else posixpath.join(folder, name)
            content = quiet(self.source.remote.read_small, path, COMPOSE_BYTES)
            if content and found_facts.mentions(content.decode("utf-8", errors="replace"), folder):
                note(plan, "compose_absolute_path", file=name)

    def images(self, plan: dict[str, Any], engine: str, members: list[dict[str, Any]]) -> None:
        refs = list(dict.fromkeys(str(_dict(row.get("Config")).get("Image") or "") for row in members))
        for ref in refs:
            if not ref or not catalogue.IMAGE_REF.match(ref):
                continue
            facts = image_facts(self.source, engine, ref) or {}
            on_target = image_facts(self.target, engine, ref) if self.target.engines.get(engine, {}).get("usable") else None
            item = {
                "ref": ref,
                "id": facts.get("id", ""),
                "bytes": facts.get("bytes"),
                "architecture": facts.get("architecture", ""),
                "on_target": bool(on_target and on_target["id"] == facts.get("id")),
                "selected": True,
            }
            if on_target and on_target["id"] != facts.get("id"):
                block(plan, "image_exists_on_target", image=ref)
            plan["images"].append(item)

    def mounts(
        self,
        plan: dict[str, Any],
        engine: str,
        members: list[dict[str, Any]],
        application: Application,
        choice: Choice,
        database_service: str,
    ) -> None:
        folder = application.project_dir
        target_folder = plan["folder"]["target"]
        seen: set[str] = set()
        for row in members:
            serves_database = bool(database_service) and (
                label(row, "service") == database_service or name_of(row) == database_service
            )
            for mount in mounts_of(row):
                if mount["type"] == "volume" and mount["name"]:
                    if mount["name"] in seen or not catalogue.VOLUME.match(mount["name"]):
                        continue
                    seen.add(mount["name"])
                    reason = "database_volume" if serves_database else (
                        "skipped" if mount["name"] in choice.skip_volumes else ""
                    )
                    size = size_of(self.source, mount["source"]) if mount["source"] else None
                    if size is None:
                        note(plan, "volume_size_unknown", volume=mount["name"])
                    item = {
                        "name": mount["name"],
                        "bytes": size,
                        "selected": not reason,
                        "reason": reason,
                        "project": label(row, "project"),
                        "volume": _volume_key(mount["name"], label(row, "project")),
                    }
                    if item["selected"]:
                        plan["source_root"] = plan["source_root"] or (
                            engine == "docker" and self.source.uid != "0"
                        )
                        plan["needs_root"] = plan["needs_root"] or engine == "docker"
                        if volume_exists(self.target, engine, mount["name"]):
                            block(plan, "volume_exists_on_target", volume=mount["name"])
                    plan["volumes"].append(item)
                elif mount["type"] == "bind" and mount["source"]:
                    source = mount["source"]
                    if source in seen or any(inside(source, system) for system in SYSTEM_PATHS):
                        continue
                    seen.add(source)
                    if folder and inside(source, folder):
                        if serves_database and source != folder:
                            excluded = relative(source, folder)
                            if excluded not in plan["folder"]["excluded"]:
                                plan["folder"]["excluded"].append(excluded)
                        continue
                    reason = "database_volume" if serves_database else ""
                    target_path = mapped(source, folder, target_folder)
                    item = {
                        "source": source,
                        "target": target_path,
                        "bytes": size_of(self.source, source),
                        "selected": not reason,
                        "reason": reason,
                        "unreadable": unreadable(self.source, source),
                    }
                    if item["selected"]:
                        plan["needs_root"] = True
                        if item["unreadable"]:
                            plan["source_root"] = True
                        if holds_anything(self.target.remote, target_path):
                            block(plan, "file_exists_on_target", path=target_path)
                    plan["binds"].append(item)

    def folder(self, plan: dict[str, Any], application: Application) -> None:
        folder = application.project_dir
        target_folder = plan["folder"]["target"]
        if not folder:
            return
        plan["folder"]["bytes"] = size_of(self.source, folder, plan["folder"]["excluded"])
        plan["folder"]["unreadable"] = unreadable(self.source, folder)
        if plan["folder"]["unreadable"]:
            plan["source_root"] = True
            note(plan, "source_sudo_needed", path=folder)
        plan["git"] = found_facts.git_facts(self.source.remote, folder)
        if plan["git"]:
            if plan["git"].get("remote_has_credentials"):
                note(plan, "git_remote_has_credentials")
            if plan["git"].get("dirty"):
                note(plan, "git_uncommitted_changes", count=plan["git"]["dirty"])
        if holds_anything(self.target.remote, target_folder):
            block(plan, "target_folder_not_empty", path=target_folder)
        parent = posixpath.dirname(target_folder.rstrip("/")) or "/"
        if not _writable_by(self.target, parent):
            plan["needs_root"] = True

    def backup_dir(self, plan: dict[str, Any], application: Application) -> None:
        folder = application.project_dir
        backup = application.remote_backup_dir
        if application.in_container:
            host = next(
                (
                    mount["source"]
                    for mount in application.mounts
                    if mount.get("source") and backup.startswith(mount.get("destination", "\0"))
                ),
                "",
            )
            if not host:
                return
            backup = host
        if not backup or (folder and inside(backup, folder)):
            return
        target = mapped(backup, folder, plan["folder"]["target"])
        plan["backup_dir"] = {
            "path": backup,
            "target": target,
            "create": not quiet(self.target.remote.exists, target, default=False),
        }
        if plan["backup_dir"]["create"]:
            plan["needs_root"] = plan["needs_root"] or not _writable_by(
                self.target, existing_ancestor(self.target.remote, target)
            )

    def env(self, plan: dict[str, Any], application: Application) -> None:
        folder = application.project_dir
        env_path = application.env_path
        if not env_path:
            return
        if application.env_in_container and not _host_mapped(application, env_path):
            plan["env"]["carried"] = "image"
            return
        host = _host_mapped(application, env_path) or env_path
        if folder and inside(host, folder):
            plan["env"]["carried"] = "folder"
        else:
            plan["env"]["carried"] = "extra"
            plan["extras"].append(
                {
                    "kind": "file",
                    "path": host,
                    "target": mapped(host, folder, plan["folder"]["target"]),
                    "bytes": None,
                    "reason": "env_outside_folder",
                }
            )
            target = mapped(host, folder, plan["folder"]["target"])
            if quiet(self.target.remote.exists, target, default=False):
                block(plan, "file_exists_on_target", path=target)
        if folder != plan["folder"]["target"]:
            content = quiet(self.source.remote.read_small, host, ENV_BYTES)
            if content and found_facts.mentions(content.decode("utf-8", errors="replace"), folder):
                note(plan, "env_mentions_folder")


def _volume_key(name: str, project: str) -> str:
    prefix = f"{project}_"
    return name[len(prefix) :] if project and name.startswith(prefix) else name


def _host_mapped(application: Application, path: str) -> str:
    from dbs.manager.applications.paths import host_path

    return host_path(application, path) or ""


def _writable_by(side: Side, folder: str) -> bool:
    entry = quiet(side.remote.lstat, folder)
    if entry is None or entry.permissions is None:
        return False
    return str(entry.uid) == side.uid and bool(entry.permissions & 0o200)


def _existing(path: Any) -> Any:
    current = path
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def python_venv(python: str) -> str:
    if "/bin/" not in python or not python.startswith("/"):
        return ""
    folder = python.rsplit("/bin/", 1)[0]
    return folder if folder not in ("/usr", "/usr/local", "") else ""


def placed_sizes(plan: Mapping[str, Any]) -> list[tuple[str, int]]:
    sizes = []
    folder = plan["folder"]
    if folder.get("target") and folder.get("bytes"):
        sizes.append((folder["target"], folder["bytes"]))
    for item in [*plan["binds"], *plan["extras"]]:
        if item.get("selected", True) and item.get("bytes"):
            sizes.append((item["target"], item["bytes"]))
    return sizes


def item_sizes(plans: Iterable[Mapping[str, Any]]) -> list[int]:
    sizes = []
    for plan in plans:
        if plan["folder"].get("bytes"):
            sizes.append(plan["folder"]["bytes"])
        for item in [*plan["binds"], *plan["extras"], *plan["volumes"], *plan["images"]]:
            if item.get("selected", True) and item.get("bytes") and not item.get("on_target"):
                sizes.append(item["bytes"])
    return sizes


def totals(plans: list[dict[str, Any]]) -> dict[str, Any]:
    sizes = item_sizes(plans)
    return {"bytes": sum(sizes), "largest": max(sizes, default=0)}


def blocked(inventory: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        *inventory.get("blockers", []),
        *(
            {**blocker, "application": plan["name"]}
            for plan in inventory.get("applications", [])
            for blocker in plan["blockers"]
        ),
    ]


def profile_for(application: Application, folder: str) -> DbsProfile:
    from dbs.manager.servers.services.connection_service import container_of

    return DbsProfile(
        python=application.python_path,
        manage=application.manage_path,
        project_dir=folder or None,
        settings_module=application.settings_module or None,
        container=container_of(application),
    )


def compose_target(application: Application) -> ContainerTarget:
    from dbs.manager.servers.services.connection_service import container_of

    target = container_of(application)
    if target is None:
        raise ValueError("Not a container application.")
    return target
