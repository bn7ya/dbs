from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.test.utils import override_settings
from django.utils import timezone

from dbs import audit
from dbs.exceptions import DBSError
from dbs.models import AuditEvent

from . import conf, paths
from .staging import TransferError

EXPORT = "manager.export"
IMPORT = "manager.import"
KEYS = "keys"
KEY_NAME = paths.KEY_FILE.name
BACKUPS = paths.BACKUPS_DIRECTORY
ROOTS = (KEYS, BACKUPS)
MINIMUM_PASSPHRASE = 12


def default_export_name():
    return f"django-dbs-manager-{timezone.now():%Y%m%d-%H%M%S}Z.dbs"


def checked_passphrase(passphrase):
    if len(passphrase) < MINIMUM_PASSPHRASE:
        raise TransferError(
            f"the passphrase needs at least {MINIMUM_PASSPHRASE} characters."
        )
    return passphrase


@contextmanager
def key_folder(data_dir) -> Iterator[Path]:
    keys = Path(data_dir) / KEYS
    if (keys / KEY_NAME).exists():
        yield keys
        return
    with tempfile.TemporaryDirectory(prefix=".export-", dir=data_dir) as holder:
        folder = paths.private_directory(Path(holder) / KEYS)
        paths.write_private(folder / KEY_NAME, settings.SECRET_KEY)
        yield folder


def export_manager(output, passphrase, *, with_backups=False):
    from dbs import write_backup

    output = str(output)
    if os.path.exists(output):
        raise TransferError(f"{output} already exists; choose another name.")
    passphrase = checked_passphrase(passphrase)
    data_dir = conf.data_dir()
    data = {"with_backups": with_backups}
    target = os.path.basename(output)
    try:
        with key_folder(data_dir) as keys:
            roots = [str(keys)]
            if with_backups:
                roots.append(str(paths.backups_path(data_dir)))
            with transaction.atomic(), override_settings(DBS_FILE_ROOTS=roots):
                entry = audit.record(EXPORT, target=target, data=data)
                summary = write_backup(output, passphrase)
                data.update(size=summary.bytes_written, sha256=summary.sha256)
                AuditEvent.objects.filter(pk=entry.pk, chain_index__isnull=True).update(
                    data=data
                )
    except Exception as exc:
        audit.safe_record(
            EXPORT,
            target=target,
            data=data,
            detail=str(exc),
            status=audit.FAILED,
            error_code=audit.error_code_for(exc),
        )
        raise
    return summary


@contextmanager
def opened_export(source) -> Iterator:
    try:
        handle = Path(source).open("rb")
    except OSError as exc:
        raise TransferError(f"cannot read {source}: {exc}") from exc
    with handle:
        yield handle


def exported_key(source, passphrase):
    from dbs.engine.restore import backup_files

    found = None
    with opened_export(source) as handle:
        try:
            for entry, content in backup_files(handle, passphrase):
                root = os.path.basename((entry.root or "").rstrip("/\\"))
                if entry.kind == "root" and root == KEYS and entry.name == KEY_NAME:
                    found = b"".join(content).decode("ascii").strip()
        except DBSError as exc:
            raise TransferError(str(exc)) from exc
    return found


def manages_servers():
    from .servers.models import Server

    return Server.all_objects.exists()


def import_manager(source, passphrase, *, replace=False):
    from dbs.engine.restore import backup_files, restore_backup

    from .backups.repositories import BackupPlanRepository

    if manages_servers() and not replace:
        raise TransferError(
            "this data directory already manages servers; pass --replace to replace them."
        )
    with opened_export(source) as handle:
        try:
            result = restore_backup(handle, passphrase, flush=True, write_files=False)
            written = write_roots(backup_files(handle, passphrase), conf.data_dir())
        except DBSError as exc:
            raise TransferError(str(exc)) from exc
    removed = mark_missing_backups()
    BackupPlanRepository().keep_within_limits()
    audit.record(
        IMPORT,
        target=os.path.basename(str(source)),
        data={
            "records": result.records_loaded,
            "files": written,
            "missing_backups": removed,
            "healed": result.healed,
        },
    )
    return result


def write_roots(files, data_dir):
    written = 0
    for entry, content in files:
        if entry.kind != "root" or not entry.root:
            continue
        name = os.path.basename(entry.root.rstrip("/\\"))
        if name not in ROOTS:
            continue
        root = paths.private_directory(Path(data_dir) / name).resolve()
        target = (root / entry.name).resolve()
        if os.path.commonpath([str(root), str(target)]) != str(root) or target == root:
            raise TransferError(
                f"the export holds a file outside {name}/: {entry.name}"
            )
        if name == BACKUPS and target.exists():
            continue
        paths.private_directory(target.parent)
        descriptor = os.open(
            target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, paths.FILE_MODE
        )
        with os.fdopen(descriptor, "wb") as handle:
            for piece in content:
                handle.write(piece)
        written += 1
    return written


def mark_missing_backups():
    from .backups.repositories import BackupFileRepository
    from .backups.storage import BackupStorage

    files = BackupFileRepository()
    storage = BackupStorage()
    now = timezone.now()
    removed = 0
    for file in files.still_stored():
        if not storage.exists(file.storage_path):
            files.update(file, removed_at=now)
            removed += 1
    return removed
