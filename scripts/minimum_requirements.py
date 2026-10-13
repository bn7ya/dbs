from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent.parent
BUNDLES = {"all", "dev"}
NAME = re.compile(r"^\s*([A-Za-z0-9_.-]+)")
LOWER_BOUND = re.compile(r">=\s*([^,;\s]+)")


def requirements(project):
    yield from project["dependencies"]
    for extra, listed in project["optional-dependencies"].items():
        if extra not in BUNDLES:
            yield from listed


def pinned(requirement):
    specifier, _, marker = requirement.partition(";")
    lower = LOWER_BOUND.search(specifier)
    if lower is None:
        return None
    pin = f"{NAME.match(specifier).group(1)}=={lower.group(1)}"
    return f"{pin}; {marker.strip()}" if marker.strip() else pin


def main():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    lines = []
    for requirement in requirements(project):
        line = pinned(requirement)
        if line and line not in lines:
            lines.append(line)
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
