from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

DEBIAN = "debian"
RHEL = "rhel"
FEDORA = "fedora"
ARCHITECTURES = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}
DEBIAN_MAJORS = frozenset({11, 12, 13})
UBUNTU_VERSIONS = frozenset({"22.04", "24.04", "26.04"})
RHEL_DISTRIBUTIONS = frozenset({"rhel", "rocky", "almalinux", "ol", "centos"})
RHEL_MAJORS = frozenset({8, 9, 10})
CENTOS_MAJORS = frozenset({9, 10})
FEDORA_MINIMUM = 41
CODENAME = re.compile(r"^[a-z]+$")
OS_RELEASE = "/etc/os-release"


@dataclass(frozen=True)
class System:
    family: str
    distribution: str
    version: str
    major: int
    codename: str
    architecture: str

    @property
    def supported(self) -> bool:
        return bool(self.family) and self.architecture in ARCHITECTURES.values()

    def describe(self) -> dict[str, object]:
        return {
            "family": self.family,
            "distribution": self.distribution,
            "version": self.version,
            "codename": self.codename,
            "architecture": self.architecture,
            "supported": self.supported,
        }


def os_release(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        key, separator, value = line.strip().partition("=")
        if not separator or not key or key.startswith("#"):
            continue
        try:
            parts = shlex.split(value)
        except ValueError:
            continue
        fields[key] = parts[0] if parts else ""
    return fields


def _major(version: str) -> int:
    head = version.split(".", 1)[0]
    return int(head) if head.isdigit() else 0


def family_of(distribution: str, version: str) -> str:
    major = _major(version)
    if distribution == "debian" and major in DEBIAN_MAJORS:
        return DEBIAN
    if distribution == "ubuntu" and version in UBUNTU_VERSIONS:
        return DEBIAN
    if distribution == "centos":
        return RHEL if major in CENTOS_MAJORS else ""
    if distribution in RHEL_DISTRIBUTIONS and major in RHEL_MAJORS:
        return RHEL
    if distribution == "fedora" and major >= FEDORA_MINIMUM:
        return FEDORA
    return ""


def system_of(text: str, machine: str) -> System:
    fields = os_release(text)
    distribution = fields.get("ID", "").lower()
    version = fields.get("VERSION_ID", "")
    codename = (
        fields.get("VERSION_CODENAME") or fields.get("UBUNTU_CODENAME") or ""
    ).lower()
    return System(
        family=family_of(distribution, version),
        distribution=distribution,
        version=version,
        major=_major(version),
        codename=codename if CODENAME.match(codename) else "",
        architecture=ARCHITECTURES.get(machine.strip(), machine.strip()),
    )
