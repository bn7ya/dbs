from __future__ import annotations

import os
from pathlib import Path

from django.db import transaction
from django.test.utils import override_settings
from django.utils import timezone

from dbs import audit
from dbs.exceptions import DBSError
from dbs.models import AuditEvent

from . import conf, paths

EXPORT = "manager.export"
IMPORT = "manager.import"
KEYS = "keys"
BACKUPS = paths.BACKUPS_DIRECTORY
ROOTS = (KEYS, BACKUPS)
MINIMUM_PASSPHRASE = 12


class TransferError(Exception):
    pass


def default_export_name():
    return f"django-dbs-manager-{timezone.now():%Y%m%d-%H%M%S}Z.dbs"


def checked_passphrase(passphrase):
    if len(passphrase) < MINIMUM_PASSPHRASE:
        raise TransferError(
            f"the passphrase needs at least {MINIMUM_PASSPHRASE} characters."
        )
    return passphrase


def export_manager(output, passphrase, *, with_backups=False):
    from dbs import write_backup

    output = str(output)
    if os.path.exists(output):
        raise TransferError(f"{output} already exists; choose another name.")
    passphrase = checked_passphrase(passphrase)
    data_dir = conf.data_dir()
    roots = [str(data_dir / KEYS)]
    if with_backups:
        roots.append(str(paths.backups_path(data_dir)))
    data = {"with_backups": with_backups}
    target = os.path.basename(output)
    try:
        with transaction.atomic(), override_settings(DBS_FILE_ROOTS=roots):
            entry = audit.record(EXPORT, target=target, data=data)
            summary = write_backup(output, passphrase)
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
    data.update(size=summary.bytes_written, sha256=summary.sha256)
    AuditEvent.objects.filter(pk=entry.pk).update(data=data)
    return summary


def import_manager(source, passphrase, *, replace=False):
    from dbs.engine.restore import backup_files, restore_backup

    from .servers.models import Server

    if Server.all_objects.exists() and not replace:
        raise TransferError(
            "this data directory already manages servers; pass --replace to replace them."
        )
    try:
        handle = Path(source).open("rb")
    except OSError as exc:
        raise TransferError(f"cannot read {source}: {exc}") from exc
    with handle:
        try:
            result = restore_backup(handle, passphrase, flush=True, write_files=False)
            written = write_roots(backup_files(handle, passphrase), conf.data_dir())
        except DBSError as exc:
            raise TransferError(str(exc)) from exc
    removed = mark_missing_backups()
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
