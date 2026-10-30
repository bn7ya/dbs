from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from urllib.parse import unquote, urlsplit

LOCAL_REQUIREMENT = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*@\s*(file:\S+)$")
SEPARATORS = re.compile(r"[-_.]+")
EDITABLE = ("-e ", "--editable")


def normalized(name: str) -> str:
    return SEPARATORS.sub("-", name).lower()


def installed_versions(listing: str) -> dict[str, str]:
    try:
        rows = json.loads(listing or "[]")
    except ValueError:
        return {}
    if not isinstance(rows, list):
        return {}
    return {
        normalized(row["name"]): row["version"]
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("name"), str) and isinstance(row.get("version"), str)
    }


def requirements_of(
    frozen: str, versions: Mapping[str, str], reachable: Callable[[str], bool]
) -> tuple[list[str], list[str]]:
    wanted: list[str] = []
    left_out: list[str] = []
    for raw in frozen.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(EDITABLE):
            left_out.append(line)
            continue
        local = LOCAL_REQUIREMENT.match(line)
        if local is None:
            wanted.append(line)
            continue
        name, location = local.groups()
        version = versions.get(normalized(name), "")
        if reachable(unquote(urlsplit(location).path)):
            wanted.append(line)
        elif version:
            wanted.append(f"{name}=={version}")
        else:
            left_out.append(name)
    return wanted, left_out
