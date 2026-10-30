from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from dbs.manager.relocation.systems import DEBIAN, FEDORA, RHEL, System

PACKAGE = re.compile(r"^[a-z0-9][a-z0-9+._-]{0,99}$")
NEEDS = (
    "basics",
    "docker",
    "podman",
    "git",
    "python",
    "nginx",
    "postgresql",
    "mariadb",
    "mysql",
    "redis",
)
DOCKER_DEBIAN_KEY = "9DC858229FC7DD38854AE2D88D81803C0EBFCD88"
DOCKER_RPM_KEY = "060A61C51B558A7F742B77AAC52FEB6B621E9F35"
DOCKER_PACKAGES = (
    "docker-ce",
    "docker-ce-cli",
    "containerd.io",
    "docker-buildx-plugin",
    "docker-compose-plugin",
)
DOCKER_KEYRING = "/etc/apt/keyrings/docker.asc"
DOCKER_APT_LIST = "/etc/apt/sources.list.d/docker.list"
DOCKER_RPM_REPO = "/etc/yum.repos.d/docker-ce.repo"
PODMAN_COMPOSE_MISSING = frozenset({("debian", 11), ("debian", 12), ("ubuntu", 22)})
RHEL_PYTHONS = {8: ("3.11", "3.12"), 9: ("3.11", "3.12"), 10: ("3.12",)}
POSTGRESQL_STREAM = "postgresql:16"


@dataclass(frozen=True)
class Repository:
    need: str
    key_url: str
    fingerprint: str
    path: str
    content: str


@dataclass
class PackagePlan:
    repositories: list[Repository] = field(default_factory=list)
    modules: list[str] = field(default_factory=list)
    packages: list[str] = field(default_factory=list)
    services: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.repositories or self.modules or self.packages)

    def describe(self) -> dict[str, object]:
        return {
            "repositories": [repository.path for repository in self.repositories],
            "modules": list(self.modules),
            "packages": list(self.packages),
            "services": list(self.services),
            "notes": list(self.notes),
            "blockers": list(self.blockers),
        }


def docker_channel(system: System) -> str:
    if system.family == DEBIAN:
        return "ubuntu" if system.distribution == "ubuntu" else "debian"
    if system.family == FEDORA:
        return "fedora"
    return "rhel" if system.distribution == "rhel" else "centos"


def docker_repository(system: System) -> Repository:
    channel = docker_channel(system)
    base = f"https://download.docker.com/linux/{channel}"
    if system.family == DEBIAN:
        return Repository(
            need="docker",
            key_url=f"{base}/gpg",
            fingerprint=DOCKER_DEBIAN_KEY,
            path=DOCKER_APT_LIST,
            content=(
                f"deb [arch={system.architecture} signed-by={DOCKER_KEYRING}] "
                f"{base} {system.codename} stable\n"
            ),
        )
    return Repository(
        need="docker",
        key_url=f"{base}/gpg",
        fingerprint=DOCKER_RPM_KEY,
        path=DOCKER_RPM_REPO,
        content=(
            "[docker-ce-stable]\n"
            "name=Docker CE Stable\n"
            f"baseurl={base}/$releasever/$basearch/stable\n"
            "enabled=1\n"
            "gpgcheck=1\n"
            f"gpgkey={base}/gpg\n"
        ),
    )


def python_packages(system: System, wanted: str = "") -> list[str]:
    if system.family == DEBIAN:
        return [
            "python3",
            "python3-venv",
            "python3-pip",
            "python3-dev",
            "build-essential",
            "pkg-config",
            "libpq-dev",
            "default-libmysqlclient-dev",
        ]
    build = ["gcc", "gcc-c++", "make", "pkgconf-pkg-config", "libpq-devel"]
    if system.family == FEDORA:
        return ["python3", "python3-devel", "python3-pip", *build, "mariadb-connector-c-devel"]
    offered = RHEL_PYTHONS.get(system.major, ())
    version = wanted if wanted in offered else ""
    if version:
        return [f"python{version}", f"python{version}-devel", f"python{version}-pip", *build]
    return ["python3", "python3-devel", "python3-pip", *build]


def python_command(system: System, wanted: str = "") -> str:
    if system.family == RHEL and wanted in RHEL_PYTHONS.get(system.major, ()):
        return f"/usr/bin/python{wanted}"
    return "/usr/bin/python3"


def packages_for(system: System, need: str, *, python: str = "") -> list[str]:
    debian = system.family == DEBIAN
    fedora = system.family == FEDORA
    if need == "basics":
        return ["ca-certificates", "curl", "gnupg" if debian else "gnupg2", "tar"]
    if need == "docker":
        return list(DOCKER_PACKAGES)
    if need == "podman":
        return ["podman", "uidmap", "podman-compose"] if debian else ["podman", "podman-compose"]
    if need == "git":
        return ["git"]
    if need == "python":
        return python_packages(system, python)
    if need == "nginx":
        return ["nginx"]
    if need == "postgresql":
        return (
            ["postgresql", "postgresql-contrib"]
            if debian
            else ["postgresql-server", "postgresql-contrib"]
        )
    if need == "mariadb":
        return ["mariadb-server"]
    if need == "mysql":
        if system.distribution == "ubuntu" or system.family == RHEL:
            return ["mysql-server"]
        return ["community-mysql-server"] if fedora else ["mariadb-server"]
    if need == "redis":
        if debian:
            return ["redis-server"]
        return ["valkey"] if fedora or system.major >= 10 else ["redis"]
    raise ValueError(f"Unknown need: {need!r}")


def service_for(system: System, need: str) -> str:
    debian = system.family == DEBIAN
    if need == "mysql":
        if debian:
            return "mysql" if system.distribution == "ubuntu" else "mariadb"
        return "mysqld"
    if need == "redis":
        if debian:
            return "redis-server"
        return "valkey" if system.family == FEDORA or system.major >= 10 else "redis"
    return {
        "docker": "docker",
        "postgresql": "postgresql",
        "mariadb": "mariadb",
        "nginx": "nginx",
    }.get(need, "")


def asked_packages(system: System, needs: Iterable[str], *, python: str = "") -> list[str]:
    if not system.supported:
        return []
    names: list[str] = []
    for need in ("basics", *needs):
        for name in packages_for(system, need, python=python):
            if name not in names:
                names.append(name)
    return names


def resolve(
    system: System,
    needs: Iterable[str],
    installed: Iterable[str],
    *,
    python: str = "",
) -> PackagePlan:
    plan = PackagePlan()
    wanted = [need for need in NEEDS if need in set(needs)]
    if not system.supported:
        plan.blockers.append("os_unsupported")
        return plan
    have = set(installed)
    for need in wanted:
        if need == "podman" and (system.distribution, system.major) in PODMAN_COMPOSE_MISSING:
            plan.blockers.append("compose_provider_unavailable")
            continue
        if need == "podman" and system.distribution == "rhel":
            plan.blockers.append("epel_required")
            continue
        if need == "mysql" and system.family == DEBIAN and system.distribution != "ubuntu":
            plan.notes.append("mysql_replaced_by_mariadb")
        names = packages_for(system, need, python=python)
        missing = [name for name in names if name not in have]
        if need == "docker" and missing:
            plan.repositories.append(docker_repository(system))
        if need == "podman" and missing and system.family == RHEL:
            plan.packages.append("epel-release")
        if need == "postgresql" and missing and system.family == RHEL and system.major in (8, 9):
            plan.modules.append(POSTGRESQL_STREAM)
        plan.packages.extend(name for name in missing if name not in plan.packages)
        service = service_for(system, need)
        if service:
            plan.services.append(service)
    if plan.packages and "basics" not in wanted:
        basics = [name for name in packages_for(system, "basics") if name not in have]
        plan.packages[:0] = [name for name in basics if name not in plan.packages]
    if not all(PACKAGE.match(name) for name in plan.packages):
        raise ValueError("A package name is not valid.")
    return plan


def missing_from_dpkg(stdout: str, asked: Iterable[str]) -> list[str]:
    installed = {
        name
        for name, _, status in (line.partition("\t") for line in stdout.splitlines())
        if status.strip().startswith("ii")
    }
    return [name for name in asked if name not in installed]


def missing_from_rpm(stdout: str, asked: Iterable[str]) -> list[str]:
    installed = {line.strip() for line in stdout.splitlines() if PACKAGE.match(line.strip())}
    return [name for name in asked if name not in installed]
