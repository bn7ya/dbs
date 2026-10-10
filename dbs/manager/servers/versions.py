from __future__ import annotations

import re

import dbs

COMPATIBLE_FROM = "0.2.2"
HEALTH_FROM = "0.5.0"
NUMBER = re.compile(r"\d+")


def parse(version: str | None) -> tuple[int, ...] | None:
    if not version:
        return None
    parts = []
    for piece in version.strip().split(".")[:3]:
        found = NUMBER.match(piece)
        if found is None:
            break
        parts.append(int(found.group(0)))
    if not parts:
        return None
    return tuple(parts + [0] * (3 - len(parts)))


def at_least(version: str | None, minimum: str) -> bool:
    parsed = parse(version)
    return parsed is not None and parsed >= parse(minimum)


def local_version() -> str:
    return dbs.__version__


def compatibility(remote_version: str | None) -> dict:
    return {
        "local_version": local_version(),
        "remote_version": remote_version,
        "installed": remote_version is not None,
        "compatible": at_least(remote_version, COMPATIBLE_FROM),
    }
