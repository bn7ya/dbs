from __future__ import annotations

import hashlib
import logging
import os
import secrets
import stat
from collections.abc import Mapping
from dataclasses import dataclass

from django.apps import apps
from django.core.exceptions import FieldDoesNotExist, SuspiciousFileOperation
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.core.files.utils import validate_file_name

from .conf import setting
from .exceptions import ConfigurationError, CorruptionError, RestoreError
from .io import can_write_into, sync_directory
from .registry import FieldType, backup_registry

logger = logging.getLogger("dbs")

READ_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NONBLOCK", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NOCTTY", 0)
    | getattr(os, "O_BINARY", 0)
)

STAGING_FLAGS = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_BINARY", 0)
)

RESTORE_ROOT_SETTINGS = "DBS_RESTORE_ROOTS, DBS_FILE_ROOTS or a ModelBackup's file_roots"


@dataclass
class FileEntry:
    kind: str
    size: int
    sha256: str
    model: str | None = None
    pk: object | None = None
    field: str | None = None
    name: str | None = None
    root: str | None = None
    offset: int = 0
    length: int = 0

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "size": self.size,
            "sha256": self.sha256,
            "model": self.model,
            "pk": self.pk,
            "field": self.field,
            "name": self.name,
            "root": self.root,
            "offset": self.offset,
            "length": self.length,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FileEntry":
        return cls(**data)


class SkippedFile(Exception):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_inside(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False


def regular_file(path: str, root: str | None = None) -> str:
    resolved = os.path.realpath(path)
    if root is not None and not is_inside(resolved, os.path.realpath(root)):
        raise SkippedFile("a symlink that leads outside its root")
    try:
        info = os.stat(resolved)
    except FileNotFoundError:
        raise SkippedFile("missing") from None
    except OSError as exc:
        raise SkippedFile(f"unreadable: {exc.strerror or exc}") from None
    if not stat.S_ISREG(info.st_mode):
        raise SkippedFile("not a regular file")
    return resolved


def _read_descriptor(path: str) -> bytes:
    try:
        descriptor = os.open(path, READ_FLAGS)
    except OSError as exc:
        raise SkippedFile(f"unreadable: {exc.strerror or exc}") from None
    with os.fdopen(descriptor, "rb") as fh:
        if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
            raise SkippedFile("not a regular file")
        try:
            return fh.read()
        except OSError as exc:
            raise SkippedFile(f"unreadable: {exc.strerror or exc}") from None


def read_regular_file(path: str, root: str | None = None) -> bytes:
    return _read_descriptor(regular_file(path, root))


def _reads_plain_files(storage) -> bool:
    return (
        isinstance(storage, FileSystemStorage)
        and getattr(storage.__class__, "_open", None) is FileSystemStorage._open
    )


def _read_through_storage(storage, name: str) -> bytes:
    try:
        with storage.open(name, "rb") as fh:
            return fh.read()
    except FileNotFoundError:
        raise SkippedFile("missing") from None
    except OSError as exc:
        raise SkippedFile(f"unreadable: {exc.strerror or exc}") from None


def read_storage_file(storage, name: str) -> bytes:
    try:
        local = storage.path(name)
    except NotImplementedError:
        return _read_through_storage(storage, name)
    except SuspiciousFileOperation:
        raise SkippedFile("outside its storage") from None
    resolved = regular_file(local, getattr(storage, "location", None))
    if _reads_plain_files(storage):
        return _read_descriptor(resolved)
    return _read_through_storage(storage, name)


def collect_instance_files(
    instance, file_field_types: dict[str, FieldType], skipped: list[str]
):
    label = f"{instance._meta.app_label}.{instance._meta.model_name}"
    for field_name, ftype in file_field_types.items():
        if ftype is FieldType.FILE:
            fobj = getattr(instance, field_name, None)
            if not fobj or not getattr(fobj, "name", None):
                continue
            try:
                data = read_storage_file(fobj.storage, fobj.name)
            except SkippedFile as reason:
                skipped.append(f"{label}.{field_name}: {fobj.name} ({reason})")
                continue
            yield (
                FileEntry(
                    kind="storage", size=len(data), sha256=_sha256(data),
                    model=label, pk=instance.pk, field=field_name, name=fobj.name,
                ),
                data,
            )
        elif ftype is FieldType.FILE_PATH:
            path = getattr(instance, field_name, None)
            if not path:
                continue
            try:
                data = read_regular_file(path)
            except SkippedFile as reason:
                skipped.append(f"{label}.{field_name}: {path} ({reason})")
                continue
            yield (
                FileEntry(
                    kind="path", size=len(data), sha256=_sha256(data),
                    model=label, pk=instance.pk, field=field_name, name=path,
                ),
                data,
            )


def collect_root_files(root: str, skipped: list[str]):
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        return
    real_root = os.path.realpath(root)

    def unreadable_directory(error):
        skipped.append(f"{error.filename} (unreadable directory: {error.strerror})")

    for dirpath, dirnames, filenames in os.walk(root, onerror=unreadable_directory):
        dirnames.sort()
        for dirname in dirnames:
            linked = os.path.join(dirpath, dirname)
            if os.path.islink(linked) and not is_inside(os.path.realpath(linked), real_root):
                skipped.append(f"{linked} (a symlink that leads outside its root)")
        for filename in sorted(filenames):
            abspath = os.path.join(dirpath, filename)
            try:
                data = read_regular_file(abspath, real_root)
            except SkippedFile as reason:
                skipped.append(f"{abspath} ({reason})")
                continue
            yield (
                FileEntry(
                    kind="root", size=len(data), sha256=_sha256(data),
                    root=root, name=os.path.relpath(abspath, root),
                ),
                data,
            )


@dataclass
class Placement:
    entry: FileEntry
    data: bytes
    target: str = ""
    storage: object = None
    name: str = ""
    moved_to: str = ""
    file_mode: int | None = None
    directory_mode: int | None = None
    problem: str = ""

    @property
    def label(self) -> str:
        return self.target or self.name or str(self.entry.name)

    def refuse(self, reason: str) -> "Placement":
        self.problem = reason
        return self


def restore_roots(registry=None) -> list[str]:
    configured = setting("DBS_RESTORE_ROOTS", None)
    if configured is None:
        configured = setting("DBS_FILE_ROOTS", None) or []
    declared = [
        root
        for _model, config in (registry or backup_registry).items()
        for root in (config.file_roots or [])
    ]
    roots: list[str] = []
    for root in [*configured, *declared]:
        resolved = os.path.realpath(root)
        if resolved not in roots:
            roots.append(resolved)
    return roots


def restore_path_map() -> dict[str, str]:
    configured = setting("DBS_RESTORE_PATH_MAP", None) or {}
    if not isinstance(configured, Mapping) or not all(
        isinstance(old, str) and isinstance(new, str) and old and new
        for old, new in configured.items()
    ):
        raise ConfigurationError(
            "DBS_RESTORE_PATH_MAP must map each old root (a path) to its new root (a path)."
        )
    return {os.path.normpath(old): os.path.normpath(new) for old, new in configured.items()}


def map_path(path: str, path_map: dict[str, str]) -> str:
    normalized = os.path.normpath(path)
    matches = [old for old in path_map if is_inside(normalized, old)]
    if not matches:
        return path
    old = max(matches, key=len)
    relative = os.path.relpath(normalized, old)
    if relative == os.curdir:
        return path_map[old]
    return os.path.join(path_map[old], relative)


def _obstacle(target: str) -> str:
    if os.path.lexists(target) and not os.path.isfile(target):
        return "something other than a file is in the way"
    if not can_write_into(os.path.dirname(target)):
        return "its directory cannot be written"
    return ""


def _place_local(placement: Placement, path: str, roots: list[str], own_root=None):
    target = os.path.realpath(path)
    if own_root is not None and not is_inside(target, os.path.realpath(own_root)):
        return placement.refuse(f"{path}: resolves outside its root {own_root}")
    if not any(is_inside(target, root) for root in roots):
        return placement.refuse(
            f"{path}: resolves outside every restore root ({RESTORE_ROOT_SETTINGS})"
        )
    obstacle = _obstacle(target)
    if obstacle:
        return placement.refuse(f"{target}: {obstacle}")
    placement.target = target
    return placement


def _place_storage(placement: Placement) -> Placement:
    entry = placement.entry
    described = f"{entry.model}.{entry.field}: {entry.name}"
    try:
        storage = apps.get_model(entry.model)._meta.get_field(entry.field).storage
    except (LookupError, FieldDoesNotExist, AttributeError, TypeError, ValueError):
        return placement.refuse(f"{described}: this project has no such file field")
    try:
        local = storage.path(entry.name)
    except NotImplementedError:
        local = None
    except SuspiciousFileOperation:
        return placement.refuse(f"{described}: resolves outside the field's storage")
    if local is None:
        try:
            validate_file_name(entry.name, allow_relative_path=True)
        except SuspiciousFileOperation:
            return placement.refuse(f"{described}: not a safe storage name")
        placement.storage = storage
        placement.name = entry.name
        return placement
    location = getattr(storage, "location", None)
    roots = [os.path.realpath(location)] if location else [os.path.dirname(os.path.realpath(local))]
    placement.file_mode = getattr(storage, "file_permissions_mode", None)
    placement.directory_mode = getattr(storage, "directory_permissions_mode", None)
    return _place_local(placement, local, roots)


def place_file(entry: FileEntry, data: bytes, roots: list[str], path_map: dict) -> Placement:
    if _sha256(data) != entry.sha256:
        raise CorruptionError(
            f"File {entry.name!r} failed its integrity hash after extraction."
        )
    placement = Placement(entry, data)
    if entry.kind == "storage":
        return _place_storage(placement)
    if entry.kind == "path":
        mapped = map_path(entry.name, path_map)
        if mapped != entry.name:
            placement.moved_to = mapped
        return _place_local(placement, mapped, roots)
    if entry.kind == "root":
        root = map_path(entry.root, path_map)
        return _place_local(placement, os.path.join(root, entry.name), roots, own_root=root)
    return placement.refuse(f"{entry.name}: unknown file entry kind {entry.kind!r}")


def plan_restore(files, *, registry=None) -> list[Placement]:
    roots = restore_roots(registry)
    path_map = restore_path_map()
    return [place_file(entry, data, roots, path_map) for entry, data in files]


def refusal_message(problems: list[str]) -> str:
    return (
        f"Refusing to restore: {len(problems)} file(s) cannot be written, so no row "
        "was loaded and no file was touched. "
        + "; ".join(problems)
        + ". Allow the directory in DBS_RESTORE_ROOTS, or map an old root to a new one "
        "with DBS_RESTORE_PATH_MAP."
    )


class StagedFiles:
    def __init__(self):
        self.pending: list = []
        self.created_directories: list[str] = []
        self.published = 0

    def stage_all(self, placements) -> None:
        try:
            for placement in placements:
                self.pending.append((self._stage(placement), placement))
        except BaseException:
            self.discard()
            raise

    def _stage(self, placement: Placement) -> str:
        token = secrets.token_hex(6)
        if placement.storage is not None:
            return placement.storage.save(
                f"{placement.name}.{token}.dbs-restore", ContentFile(placement.data)
            )
        directory = os.path.dirname(placement.target)
        self._make_directories(directory, placement.directory_mode)
        staging = os.path.join(
            directory, f".{os.path.basename(placement.target)}.{token}.dbs-restore"
        )
        descriptor = os.open(staging, STAGING_FLAGS, 0o666)
        try:
            with os.fdopen(descriptor, "wb") as fh:
                fh.write(placement.data)
                fh.flush()
                os.fsync(fh.fileno())
            mode = _final_mode(placement)
            if mode is not None:
                os.chmod(staging, mode)
        except BaseException:
            _remove_quietly(staging)
            raise
        return staging

    def _make_directories(self, directory: str, mode) -> None:
        missing = []
        probe = directory
        while not os.path.exists(probe):
            missing.append(probe)
            parent = os.path.dirname(probe)
            if parent == probe:
                break
            probe = parent
        for path in reversed(missing):
            try:
                os.mkdir(path)
            except FileExistsError:
                continue
            self.created_directories.append(path)
            if mode is not None:
                os.chmod(path, mode)

    def publish(self) -> None:
        failures = []
        pending, self.pending = self.pending, []
        for staging, placement in pending:
            try:
                _publish(staging, placement)
                self.published += 1
            except Exception as exc:
                failures.append(f"{placement.label}: {exc}")
                _discard(staging, placement)
        if failures:
            raise RestoreError(
                "The rows were restored, but these files could not be moved into place: "
                + "; ".join(failures)
            )

    def discard(self) -> None:
        pending, self.pending = self.pending, []
        for staging, placement in pending:
            _discard(staging, placement)
        for directory in reversed(self.created_directories):
            try:
                os.rmdir(directory)
            except OSError:
                pass
        self.created_directories = []


def _final_mode(placement: Placement):
    if placement.file_mode is not None:
        return placement.file_mode
    try:
        return stat.S_IMODE(os.stat(placement.target).st_mode)
    except FileNotFoundError:
        return None


def _publish(staging: str, placement: Placement) -> None:
    if placement.storage is None:
        os.replace(staging, placement.target)
        sync_directory(os.path.dirname(placement.target))
        return
    storage = placement.storage
    if storage.exists(placement.name):
        storage.delete(placement.name)
    saved = storage.save(placement.name, ContentFile(placement.data))
    storage.delete(staging)
    if saved != placement.name:
        logger.warning(
            "storage saved %s as %s; the restored row still names %s",
            placement.name,
            saved,
            placement.name,
        )


def _discard(staging: str, placement: Placement) -> None:
    if placement.storage is None:
        _remove_quietly(staging)
        return
    try:
        placement.storage.delete(staging)
    except Exception:
        logger.warning("could not remove the staging file %s", staging)


def _remove_quietly(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def restore_file(entry: FileEntry, data: bytes, registry=None) -> None:
    placement = plan_restore([(entry, data)], registry=registry)[0]
    if placement.problem:
        raise RestoreError(refusal_message([placement.problem]))
    staged = StagedFiles()
    staged.stage_all([placement])
    staged.publish()
