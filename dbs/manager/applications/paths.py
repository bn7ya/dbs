from __future__ import annotations

import posixpath
from typing import Any


def on_host(mounts: list[dict[str, Any]], path: str) -> str | None:
    best = None
    for mount in mounts or ():
        destination = str(mount.get("destination") or "").rstrip("/") or "/"
        source = str(mount.get("source") or "")
        if not source or not _inside(path, destination):
            continue
        if best is None or len(destination) > len(best[0]):
            best = (destination, source)
    if best is None:
        return None
    destination, source = best
    remainder = posixpath.relpath(path, destination)
    return source if remainder == "." else posixpath.join(source, remainder)


def host_path(application: Any, path: str) -> str | None:
    if not path:
        return None
    if not application.in_container:
        return path
    return on_host(application.mounts, path)


def _inside(path: str, folder: str) -> bool:
    if folder == "/":
        return path.startswith("/")
    return path == folder or path.startswith(folder + "/")
