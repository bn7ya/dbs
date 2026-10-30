from __future__ import annotations

import hashlib
import posixpath
import re
import secrets
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dbs.manager.paths import private_directory
from dbs.manager.relocation import catalogue
from dbs.manager.relocation.catalogue import Command
from dbs.manager.relocation.exceptions import (
    PrivilegedCommandFailed,
    TargetFileExists,
    TargetFolderNotEmpty,
    TransferDigestMismatch,
)
from dbs.manager.relocation.privileged import Privileged
from dbs.manager.servers.exceptions import RemoteCommandFailed
from dbs.manager.servers.gateways import EntryKind

FOLDER = "folder"
FILE = "file"
IMAGE = "image"
VOLUME = "volume"
PODMAN_VOLUME = "podman_volume"
UPLOAD_ATTEMPTS = 3
TAR_FILES_CHANGED = 1
SAFE_KEY = re.compile(r"[^A-Za-z0-9_.-]+")
STAGED_MODE = 0o600

Progress = Callable[[str, int, "int | None"], None]


@dataclass(frozen=True)
class Item:
    key: str
    kind: str
    read: Command
    target: str
    numeric: bool = True
    engine: str = ""
    labels: tuple[tuple[str, str], ...] = ()
    expected_id: str = ""
    size: int | None = None
    owner: tuple[str, str, str] = ()


@dataclass
class Spooled:
    path: Path
    sha256: str
    size: int
    warning: str = ""


class HashingSink:
    def __init__(self, handle: Any) -> None:
        self.handle = handle
        self.digest = hashlib.sha256()
        self.size = 0

    def write(self, data: bytes) -> int:
        self.handle.write(data)
        self.digest.update(data)
        self.size += len(data)
        return len(data)


@dataclass
class Carrier:
    source: Privileged
    target: Privileged
    spool: Path
    staging: str
    source_ids: tuple[str, str]
    target_ids: tuple[str, str]
    progress: Progress | None = None
    selinux: bool = False
    leftovers: list[str] = field(default_factory=list)

    def carry(self, item: Item) -> dict[str, Any]:
        spooled = self.fetch(item)
        try:
            staged = self.upload(item, spooled)
        finally:
            with suppress(OSError):
                spooled.path.unlink()
        try:
            outcome = self.place(item, staged)
        finally:
            self.remove_staged(staged)
        outcome.update({"bytes": spooled.size, "sha256": spooled.sha256})
        if spooled.warning:
            outcome["warning"] = spooled.warning
        return outcome

    def fetch(self, item: Item) -> Spooled:
        private_directory(self.spool)
        path = self.spool / f"{SAFE_KEY.sub('-', item.key)[:80]}-{secrets.token_hex(4)}"
        with path.open("xb") as handle:
            sink = HashingSink(handle)

            def moved(count: int) -> None:
                if self.progress is not None:
                    self.progress(item.key, sink.size, item.size)

            try:
                result = self.source.stream(item.read, sink, progress=moved)
            except BaseException:
                handle.close()
                with suppress(OSError):
                    path.unlink()
                raise
        warning = ""
        if not result.ok:
            if item.read.argv[:2] == ("tar", "--create") and result.exit_status == TAR_FILES_CHANGED:
                warning = "files_changed"
            else:
                with suppress(OSError):
                    path.unlink()
                raise PrivilegedCommandFailed(output=self.source.scrub(result.stderr))
        return Spooled(path, sink.digest.hexdigest(), sink.size, warning)

    def upload(self, item: Item, spooled: Spooled) -> str:
        self.target.remote.ensure_folder(self.staging)
        for _ in range(UPLOAD_ATTEMPTS):
            name = f"{SAFE_KEY.sub('-', item.key)[:80]}-{secrets.token_hex(4)}"
            with spooled.path.open("rb") as handle:
                entry = self.target.remote.write_new(handle, self.staging, name, mode=STAGED_MODE)
            if self.target.remote.sha256(entry.path) == spooled.sha256:
                return entry.path
            self.remove_staged(entry.path)
        raise TransferDigestMismatch()

    def remove_staged(self, staged: str) -> None:
        try:
            self.target.remote.remove_file(staged)
        except RemoteCommandFailed:
            self.leftovers.append(staged)

    def place(self, item: Item, staged: str) -> dict[str, Any]:
        if item.kind == FOLDER:
            return self.place_folder(item, staged)
        if item.kind == FILE:
            return self.place_file(item, staged)
        if item.kind == IMAGE:
            return self.load_image(item, staged)
        if item.kind == VOLUME:
            return self.fill_volume(item, staged)
        if item.kind == PODMAN_VOLUME:
            return self.import_volume(item, staged)
        raise ValueError(f"Unknown item kind: {item.kind!r}")

    @property
    def as_root(self) -> bool:
        return self.target.mode != catalogue.MISSING

    def incoming(self, destination: str) -> str:
        parent = posixpath.dirname(destination.rstrip("/")) or "/"
        name = posixpath.basename(destination.rstrip("/"))
        if not self.target.remote.exists(parent):
            self.make(parent)
        folder = posixpath.join(parent, f".{name}.dbs-incoming-{secrets.token_hex(4)}")
        self.make(folder)
        return folder

    def make(self, folder: str) -> None:
        if self.as_root:
            self.target.run(catalogue.make_folder(folder, "0755", "0", "0"))
        else:
            self.target.remote.ensure_folder(folder)

    def extract(self, staged: str, into: str, numeric: bool) -> None:
        self.target.run(catalogue.tar_extract(staged, into, numeric=numeric, root=self.as_root))

    def remap(self, folder: str) -> None:
        if not self.as_root:
            return
        source_uid, source_gid = self.source_ids
        target_uid, target_gid = self.target_ids
        if source_uid and target_uid and source_uid != target_uid:
            self.target.run(catalogue.own_user(folder, source_uid, target_uid))
        if source_gid and target_gid and source_gid != target_gid:
            self.target.run(catalogue.own_group(folder, source_gid, target_gid))
        if self.selinux:
            self.target.run(catalogue.restore_contexts(folder), check=False)

    def settle(self, incoming: str, destination: str) -> None:
        remote = self.target.remote
        if remote.lexists(destination):
            entry = remote.lstat(destination)
            if entry.kind != EntryKind.FOLDER or remote.listdir(destination):
                self.leftovers.append(incoming)
                raise TargetFolderNotEmpty()
            self.target.run(catalogue.remove_empty_folder(destination, root=self.as_root))
        self.target.run(catalogue.place(incoming, destination, root=self.as_root))
        if remote.lexists(incoming):
            self.leftovers.append(incoming)
            raise TargetFolderNotEmpty()

    def place_folder(self, item: Item, staged: str) -> dict[str, Any]:
        incoming = self.incoming(item.target)
        try:
            self.extract(staged, incoming, item.numeric)
            self.adopt(incoming, item.owner)
            self.remap(incoming)
        except BaseException:
            self.leftovers.append(incoming)
            raise
        self.settle(incoming, item.target)
        return {"placed": item.target}

    def adopt(self, folder: str, owner: tuple[str, str, str]) -> None:
        if not owner:
            return
        uid, gid, mode = owner
        if self.as_root:
            self.target.run(catalogue.own_folder(folder, uid, gid))
        self.target.run(catalogue.folder_mode(folder, mode, root=self.as_root))

    def place_file(self, item: Item, staged: str) -> dict[str, Any]:
        remote = self.target.remote
        if remote.lexists(item.target):
            raise TargetFileExists()
        incoming = self.incoming(item.target)
        try:
            self.extract(staged, incoming, item.numeric)
            self.remap(incoming)
            name = posixpath.basename(item.target)
            self.target.run(
                catalogue.place(posixpath.join(incoming, name), item.target, root=self.as_root)
            )
        except BaseException:
            self.leftovers.append(incoming)
            raise
        if not remote.lexists(item.target):
            self.leftovers.append(incoming)
            raise TargetFileExists()
        self.target.run(catalogue.remove_empty_folder(incoming, root=self.as_root), check=False)
        if remote.lexists(incoming):
            self.leftovers.append(incoming)
        return {"placed": item.target}

    def load_image(self, item: Item, staged: str) -> dict[str, Any]:
        self.target.run(catalogue.image_load(item.engine, staged))
        loaded = self.target.run(catalogue.image_facts(item.engine, item.target), check=False)
        found = loaded.stdout.strip().split()[0] if loaded.ok and loaded.stdout.strip() else ""
        outcome: dict[str, Any] = {"loaded": item.target, "id": found}
        if item.expected_id and found and found != item.expected_id:
            outcome["warning"] = "image_id_changed"
        return outcome

    def fill_volume(self, item: Item, staged: str) -> dict[str, Any]:
        self.target.run(catalogue.volume_create(item.engine, item.target, dict(item.labels)))
        found = self.target.run(catalogue.volume_mountpoint(item.engine, item.target))
        mountpoint = found.stdout.strip()
        if self.target.remote.listdir(mountpoint):
            raise TargetFolderNotEmpty()
        self.extract(staged, mountpoint, True)
        return {"volume": item.target}

    def import_volume(self, item: Item, staged: str) -> dict[str, Any]:
        self.target.run(catalogue.volume_create("podman", item.target, dict(item.labels)))
        self.target.run(catalogue.volume_import(item.target, staged))
        return {"volume": item.target}
