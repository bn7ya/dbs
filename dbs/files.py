from __future__ import annotations

import hashlib
import logging
import os
import stat
from dataclasses import dataclass

from django.apps import apps
from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage

from .registry import FieldType

logger = logging.getLogger("dbs")

READ_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NONBLOCK", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NOCTTY", 0)
    | getattr(os, "O_BINARY", 0)
)

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


def restore_file(entry: FileEntry, data: bytes) -> None:
    if _sha256(data) != entry.sha256:
        from .exceptions import CorruptionError

        raise CorruptionError(
            f"File {entry.name!r} failed its integrity hash after extraction."
        )

    if entry.kind == "storage":
        _restore_storage_file(entry, data)
    elif entry.kind == "path":
        _write_path(entry.name, data)
    elif entry.kind == "root":
        _write_path(os.path.join(entry.root, entry.name), data)
    else:
        from .exceptions import RestoreError

        raise RestoreError(f"Unknown file entry kind: {entry.kind!r}")


def _restore_storage_file(entry: FileEntry, data: bytes) -> None:
    model = apps.get_model(entry.model)
    storage = model._meta.get_field(entry.field).storage
    safety_name = storage.save(entry.name + ".dbs-restore", ContentFile(data))
    if storage.exists(entry.name):
        storage.delete(entry.name)
    storage.save(entry.name, ContentFile(data))
    storage.delete(safety_name)


def _restore_roots() -> list[str]:
    configured = getattr(settings, "DBS_RESTORE_ROOTS", None)
    if configured is None:
        configured = getattr(settings, "DBS_FILE_ROOTS", []) or []
    return [os.path.realpath(root) for root in configured]


def _confined_path(path: str) -> str:
    target = os.path.realpath(path)
    for root in _restore_roots():
        try:
            if os.path.commonpath([target, root]) == root:
                return target
        except ValueError:
            continue
    from .exceptions import RestoreError

    raise RestoreError(
        f"Refusing to write {path!r}: the target resolves outside every "
        "configured restore root (DBS_RESTORE_ROOTS or DBS_FILE_ROOTS)."
    )


def _write_path(path: str, data: bytes) -> None:
    target = _confined_path(path)
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    partial = target + ".dbs-tmp"
    with open(partial, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(partial, target)
