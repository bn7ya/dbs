"""Reading file bytes for backup and writing them back on restore.

Three kinds of file references are supported, matching the three file-ish
:class:`~dbs.registry.FieldType` values plus extra non-model roots:

* ``storage`` -- a ``FileField``/``ImageField``; bytes come from the field's
  Django ``Storage`` and are restored to the same storage + name.
* ``path``    -- a string column holding a filesystem path; bytes come from that
  path and are restored to the same path.
* ``root``    -- a whole directory tree registered via ``file_roots``; every file
  underneath is embedded and restored relative to that root.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

from django.apps import apps
from django.core.files.base import ContentFile

from .registry import FieldType


@dataclass
class FileEntry:
    """A backed-up file's metadata (the bytes are stored separately)."""

    kind: str            # "storage" | "path" | "root"
    size: int
    sha256: str
    model: str | None = None
    pk: object | None = None
    field: str | None = None
    name: str | None = None   # storage name, absolute path, or relpath under root
    root: str | None = None   # base directory for kind == "root"
    offset: int = 0           # position of the bytes in the payload blob
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


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def collect_instance_files(instance, file_field_types: dict[str, FieldType]):
    """Yield ``(FileEntry, bytes)`` for the file-bearing fields of ``instance``."""
    label = f"{instance._meta.app_label}.{instance._meta.model_name}"
    for field_name, ftype in file_field_types.items():
        if ftype is FieldType.FILE:
            fobj = getattr(instance, field_name, None)
            if not fobj or not getattr(fobj, "name", None):
                continue
            try:
                with fobj.storage.open(fobj.name, "rb") as fh:
                    data = fh.read()
            except (FileNotFoundError, OSError):
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
            if not path or not os.path.isfile(path):
                continue
            with open(path, "rb") as fh:
                data = fh.read()
            yield (
                FileEntry(
                    kind="path", size=len(data), sha256=_sha256(data),
                    model=label, pk=instance.pk, field=field_name, name=path,
                ),
                data,
            )


def collect_root_files(root: str):
    """Yield ``(FileEntry, bytes)`` for every file under directory ``root``."""
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        return
    for dirpath, _dirs, filenames in os.walk(root):
        for filename in filenames:
            abspath = os.path.join(dirpath, filename)
            relpath = os.path.relpath(abspath, root)
            try:
                with open(abspath, "rb") as fh:
                    data = fh.read()
            except OSError:
                continue
            yield (
                FileEntry(
                    kind="root", size=len(data), sha256=_sha256(data),
                    root=root, name=relpath,
                ),
                data,
            )


def restore_file(entry: FileEntry, data: bytes) -> None:
    """Write ``data`` back to the location described by ``entry``."""
    if _sha256(data) != entry.sha256:
        from .exceptions import CorruptionError

        raise CorruptionError(
            f"File '{entry.name}' failed its integrity hash after extraction."
        )

    if entry.kind == "storage":
        model = apps.get_model(entry.model)
        storage = model._meta.get_field(entry.field).storage
        if storage.exists(entry.name):
            storage.delete(entry.name)
        storage.save(entry.name, ContentFile(data))
    elif entry.kind == "path":
        _write_path(entry.name, data)
    elif entry.kind == "root":
        _write_path(os.path.join(entry.root, entry.name), data)
    else:  # pragma: no cover - guarded by construction
        from .exceptions import RestoreError

        raise RestoreError(f"Unknown file entry kind: {entry.kind!r}")


def _write_path(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
