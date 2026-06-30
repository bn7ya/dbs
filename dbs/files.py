from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

from django.apps import apps
from django.core.files.base import ContentFile

from .registry import FieldType


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


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def collect_instance_files(instance, file_field_types: dict[str, FieldType]):
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
    else:
        from .exceptions import RestoreError

        raise RestoreError(f"Unknown file entry kind: {entry.kind!r}")


def _write_path(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
