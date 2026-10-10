from __future__ import annotations

import posixpath
import stat
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

from rest_framework.exceptions import APIException

from dbs.manager.servers.gateways import EntryKind, RemoteHost

VERSION_PROBE = (
    "import sys; sys.path[:] = [p for p in sys.path if p not in ('', '.')]; "
    "import dbs; print(dbs.__version__)"
)
NAMED_VENVS = (".venv", "venv", "env")
VENV_MARKER = "pyvenv.cfg"
VENV_PYTHON = ("bin", "python")
ROOT_ID = 0
VIRTUALENVS_HOME = ".virtualenvs"
BARE_PYTHONS = ("python3", "python")
FOLDERS_PER_LOCATION = 100
PROBES_PER_SEARCH = 8
REPORTED_OUTPUT_LIMIT = 200

T = TypeVar("T")


@dataclass(frozen=True)
class Probe:
    version: str | None
    error: str


@dataclass(frozen=True)
class Found:
    python_path: str
    dbs_version: str


def quiet(call: Callable[..., T], *args: Any, default: T | None = None) -> T | None:
    try:
        return call(*args)
    except APIException:
        return default


@dataclass(frozen=True)
class Owners:
    uids: frozenset[int]
    gids: frozenset[int]


def owners(remote: RemoteHost) -> Owners:
    home = quiet(remote.realpath, ".")
    entry = quiet(remote.lstat, home) if home else None
    uids = {ROOT_ID} if entry is None or entry.uid is None else {ROOT_ID, entry.uid}
    gids = {ROOT_ID} if entry is None or entry.gid is None else {ROOT_ID, entry.gid}
    return Owners(uids=frozenset(uids), gids=frozenset(gids))


def trusted(remote: RemoteHost, folder: str, allowed: Owners) -> bool:
    entry = quiet(remote.lstat, folder)
    if (
        entry is None
        or entry.kind != EntryKind.FOLDER
        or entry.uid not in allowed.uids
        or entry.permissions is None
    ):
        return False
    group_may_write = bool(entry.permissions & stat.S_IWGRP)
    return not entry.permissions & stat.S_IWOTH and (
        not group_may_write or entry.gid in allowed.gids
    )


def trusted_with_parent(remote: RemoteHost, folder: str) -> bool:
    allowed = owners(remote)
    return trusted(remote, posixpath.dirname(folder), allowed) and trusted(
        remote, folder, allowed
    )


def candidates(remote: RemoteHost, project: str) -> list[str]:
    allowed = owners(remote)
    found: list[str] = []
    if project:
        found += _named_venvs(remote, project)
        for folder in (project, posixpath.dirname(project)):
            found += _marked_venvs(remote, folder)
    home = quiet(remote.realpath, ".")
    if home:
        found += _marked_venvs(remote, posixpath.join(home, VIRTUALENVS_HOME))
    usable = [python for python in found if _trusted_venv(remote, python, allowed)]
    return list(dict.fromkeys([*usable, *BARE_PYTHONS]))


def probe(remote: RemoteHost, python: str, cwd: str | None) -> Probe:
    try:
        result = remote.run([python, "-c", VERSION_PROBE], cwd=cwd)
    except APIException:
        return Probe(version=None, error="")
    output = result.stdout.strip().splitlines()
    errors = result.stderr.strip().splitlines()
    error = errors[-1][:REPORTED_OUTPUT_LIMIT] if errors else ""
    if not result.ok or not output:
        return Probe(version=None, error=error)
    return Probe(version=output[-1][:REPORTED_OUTPUT_LIMIT], error="")


def with_dbs(
    remote: RemoteHost, pythons: Sequence[str], cwd: str | None
) -> Found | None:
    for python in _bounded(pythons):
        version = probe(remote, python, cwd).version
        if version is not None:
            return Found(python_path=python, dbs_version=version)
    return None


def _bounded(pythons: Sequence[str]) -> list[str]:
    bare = [python for python in pythons if python in BARE_PYTHONS]
    venvs = [python for python in pythons if python not in BARE_PYTHONS]
    return [*venvs[: PROBES_PER_SEARCH - len(bare)], *bare]


def _trusted_venv(remote: RemoteHost, python: str, allowed: Owners) -> bool:
    bin_folder = posixpath.dirname(python)
    venv = posixpath.dirname(bin_folder)
    return all(
        trusted(remote, folder, allowed)
        for folder in (posixpath.dirname(venv), venv, bin_folder)
    )


def _named_venvs(remote: RemoteHost, project: str) -> list[str]:
    pythons = [posixpath.join(project, name, *VENV_PYTHON) for name in NAMED_VENVS]
    return [path for path in pythons if quiet(remote.exists, path, default=False)]


def _marked_venvs(remote: RemoteHost, folder: str) -> list[str]:
    entries = quiet(remote.listdir, folder, default=[]) or []
    folders = sorted(
        (entry for entry in entries if entry.kind == EntryKind.FOLDER),
        key=lambda entry: entry.name,
    )[:FOLDERS_PER_LOCATION]
    return [
        posixpath.join(folder, entry.name, *VENV_PYTHON)
        for entry in folders
        if quiet(
            remote.exists,
            posixpath.join(folder, entry.name, VENV_MARKER),
            default=False,
        )
    ]
