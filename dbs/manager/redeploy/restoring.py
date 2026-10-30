from __future__ import annotations

from typing import Any
from uuid import UUID

from django.conf import settings

from dbs import validate_backup
from dbs.manager.applications.models import Application
from dbs.manager.backups.exceptions import BackupMissing
from dbs.manager.backups.models import BackupFile
from dbs.manager.backups.repositories import BackupFileRepository
from dbs.manager.backups.storage import BackupStorage
from dbs.manager.servers.exceptions import RestoreFailed
from dbs.manager.servers.services import ServerConnectionService

Detail = dict[str, Any]


def manage(target: Application, actor: Any, *arguments: str) -> Any:
    connections = ServerConnectionService(actor)
    with connections.open(target) as remote:
        return remote.run_manage(
            connections.dbs_profile(target),
            arguments,
            timeout=settings.BACKUP_EXEC_TIMEOUT,
        )


def migrated(target: Application, actor: Any) -> bool:
    return bool(manage(target, actor, "migrate", "--check", "--noinput").ok)


def stored(file_id: str) -> BackupFile:
    file = BackupFileRepository().find_including_deleted(UUID(file_id))
    if file is None or file.removed_at is not None:
        raise BackupMissing()
    return file


def validate(file: BackupFile, actor: Any) -> Detail:
    passphrase = ServerConnectionService(actor).backup_passphrase(file.application)
    try:
        with BackupStorage().open_read(file.storage_path) as handle:
            result = validate_backup(handle, passphrase)
    except FileNotFoundError as exc:
        raise BackupMissing() from exc
    if not (result.ok and result.decrypted_ok):
        raise RestoreFailed()
    return {"validated": True, "target_not_migrated": True}


def restore_file(
    file: BackupFile,
    target: Application,
    actor: Any,
    *,
    flush: bool,
    dry_run: bool,
) -> Detail:
    connections = ServerConnectionService(actor)
    try:
        handle = BackupStorage().open_read(file.storage_path)
    except FileNotFoundError as exc:
        raise BackupMissing() from exc
    with handle, connections.open(target) as remote:
        report = remote.restore_dbs_backup(
            handle,
            profile=connections.dbs_profile(target),
            passphrase=connections.backup_passphrase(file.application),
            remote_dir=connections.staging_folder(target, remote),
            flush=flush,
            dry_run=dry_run,
        )
    outcome: Detail = {
        "backup": str(file.pk),
        "records": report.records,
        "files": report.files,
        "flushed": report.flushed,
        "healed": report.healed,
    }
    if report.copy_left:
        outcome["copy_left"] = report.copy_left
    return outcome
