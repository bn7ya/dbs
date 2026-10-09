from __future__ import annotations

import posixpath


def absolute_path(path: str) -> str | None:
    if not path.startswith("/") or "\x00" in path or ".." in path.split("/"):
        return None
    return "/" + posixpath.normpath(path).lstrip("/")
