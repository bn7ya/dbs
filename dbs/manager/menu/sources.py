from __future__ import annotations

import os
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from . import commands, running

FOLDER = "folder"
FILE = "file"
LINK = "link"
OTHER = "other"
LOCAL_LIMIT = 5000


class Unreadable(Exception):
    pass


@dataclass(frozen=True)
class Entry:
    name: str
    path: str
    kind: str
    size: Optional[int] = None
    modified: str = ""
    mode: str = ""

    @property
    def opens(self) -> bool:
        return self.kind == FOLDER


@dataclass
class Folder:
    path: str
    parent: Optional[str]
    entries: list
    roots: list = field(default_factory=list)
    note: str = ""


class LocalDisk:
    title = "This computer"
    changes = False

    def __init__(self, start: str = "") -> None:
        self.start = start or os.getcwd()

    def list(self, path: Optional[str]) -> Folder:
        place = Path(path or self.start).expanduser()
        try:
            place = place.resolve()
            found = sorted(os.scandir(place), key=lambda item: item.name.casefold())
        except OSError as exc:
            raise Unreadable(f"{place}: {exc.strerror or exc}") from exc
        entries = [_local(item) for item in found[:LOCAL_LIMIT]]
        entries.sort(key=lambda entry: (not entry.opens, entry.name.casefold()))
        parent = str(place.parent) if place.parent != place else None
        note = "Only the first entries are shown." if len(found) > LOCAL_LIMIT else ""
        return Folder(str(place), parent, entries, [str(Path.home())], note)


def _local(item: os.DirEntry) -> Entry:
    try:
        details = item.stat()
        folder = item.is_dir()
    except OSError:
        return Entry(item.name, item.path, OTHER)
    kind = FOLDER if folder else FILE if stat.S_ISREG(details.st_mode) else OTHER
    return Entry(
        item.name,
        item.path,
        kind,
        None if folder else details.st_size,
        time.strftime("%Y-%m-%d %H:%M", time.localtime(details.st_mtime)),
        stat.filemode(details.st_mode)[1:],
    )


class Remote:
    changes = False
    path = ()
    owner = ""
    title = ""

    def __init__(self, app: Any, reference: str, name: str) -> None:
        self.app = app
        self.reference = reference
        self.title = name

    def list(self, path: Optional[str]) -> Folder:
        verb = commands.verb(*self.path)
        values = {self.owner: self.reference, "<path>": path or ""}
        outcome = running.run(self.app, verb, values, quiet=True)
        table = outcome.table()
        if not outcome.ok or table is None or not isinstance(table.data, dict):
            raise Unreadable(outcome.problem or "the folder could not be read.")
        return self.folder(table.data)

    def folder(self, listing: dict) -> Folder:
        raise NotImplementedError


class ApplicationFiles(Remote):
    changes = True
    path = ("files", "list")
    owner = "<application>"

    def folder(self, listing: dict) -> Folder:
        return Folder(
            listing["path"],
            listing.get("parent"),
            [_remote(entry) for entry in listing["results"]],
            list(listing.get("roots") or ()),
        )


class ServerFolders(Remote):
    path = ("server", "browse")
    owner = "<server>"

    def folder(self, listing: dict) -> Folder:
        notes = []
        if listing.get("project"):
            notes.append("A Django project.")
        if listing.get("truncated"):
            notes.append("Only the first entries are shown.")
        roots = [listing["home"]] if listing.get("home") else []
        return Folder(
            listing["path"],
            listing.get("parent"),
            [_remote(entry) for entry in listing["results"]],
            roots,
            " ".join(notes),
        )


def _remote(entry: dict) -> Entry:
    return Entry(
        entry["name"],
        entry["path"],
        entry["kind"],
        entry.get("size"),
        str(entry.get("modified") or "")[:16].replace("T", " "),
        entry.get("mode", ""),
    )
