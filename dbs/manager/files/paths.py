from __future__ import annotations

import posixpath
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from rest_framework.exceptions import ErrorDetail, ValidationError

from dbs.manager.common.paths import absolute_path
from dbs.manager.files.exceptions import NoAllowedFolders, PathOutsideRoots

NAME_MAX_BYTES = 255
ABSOLUTE_PATH_REQUIRED = (
    "Use an absolute path that starts with / and has no '..' in it."
)


@dataclass(frozen=True)
class Located:
    path: str
    root: str

    @property
    def parent(self) -> str | None:
        return None if self.path == self.root else posixpath.dirname(self.path)

    @property
    def name(self) -> str:
        return posixpath.basename(self.path)


def allowed_roots(roots: Iterable[str]) -> list[str]:
    normalised = (absolute_path(root) for root in roots)
    return list(dict.fromkeys(root for root in normalised if root is not None))


def within(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def locate(typed: str, roots: Sequence[str]) -> Located:
    if not roots:
        raise NoAllowedFolders()
    path = absolute_path(typed)
    if path is None:
        raise ValidationError(
            {
                "path": [
                    ErrorDetail(ABSOLUTE_PATH_REQUIRED, code="absolute_path_required")
                ]
            }
        )
    holding = [root for root in roots if within(path, root)]
    if not holding:
        raise PathOutsideRoots()
    return Located(path=path, root=max(holding, key=len))


def resolved(answer: str, real_roots: Sequence[str]) -> str:
    path = absolute_path(answer)
    if path is None or not any(within(path, root) for root in real_roots):
        raise PathOutsideRoots()
    return path


def entry_name(typed: str) -> str | None:
    if (
        typed in {"", ".", ".."}
        or "/" in typed
        or "\\" in typed
        or not typed.isprintable()
    ):
        return None
    if len(typed.encode()) > NAME_MAX_BYTES:
        return None
    return typed
