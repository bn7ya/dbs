from __future__ import annotations

import hashlib
import logging
import zlib
from dataclasses import dataclass, field

import django
from django.apps import apps
from django.db import connections, transaction

from ..conf import setting
from ..container import repair_copies
from ..container.blocks import BlockPlan, RepairReport
from ..container.format import read_container
from ..crypto import decrypt_payload
from ..crypto.envelope import EnvelopeMaterial
from ..exceptions import ContainerError, CorruptionError
from ..files import restore_file
from ..introspect import topological_order
from ..serialize import load_records
from .backup import migration_state
from .payload import unpack_payload

logger = logging.getLogger("dbs")

SUPPORTED_MANIFEST_VERSION = 1

DEFAULT_MAX_PAYLOAD_BYTES = 4 * 1024 ** 3


class _DryRunRollback(Exception):
    pass


@dataclass
class ReadResult:
    manifest: dict
    document: dict
    records: list
    files: list
    repair_report: RepairReport


@dataclass
class RestoreResult:
    records_loaded: int = 0
    files_written: int = 0
    repair_report: RepairReport | None = None
    models: list = field(default_factory=list)
    records_would_load: int = 0
    files_would_write: int = 0
    records_flushed: int = 0
    preexisting_models: list = field(default_factory=list)

    @property
    def healed(self) -> bool:
        return bool(self.repair_report and self.repair_report.healed)


def read_payload(data: bytes, passphrase: str) -> ReadResult:
    manifest, copy_a, copy_b = read_container(data)
    if int(manifest.get("version", 0)) != SUPPORTED_MANIFEST_VERSION:
        raise ContainerError(
            f"Unsupported backup manifest version {manifest.get('version')!r}; "
            f"this build of DBS reads version {SUPPORTED_MANIFEST_VERSION}."
        )
    plan = BlockPlan.from_dict(manifest["blocks"])

    ciphertext, report = repair_copies(copy_a, copy_b, plan)
    if ciphertext is None:
        raise CorruptionError(
            "Backup is damaged beyond repair: " + report.summary(), report
        )
    if report.healed:
        logger.warning("corruption detected and healed: %s", report.summary())

    material = EnvelopeMaterial.from_dict(manifest["crypto"])
    body = decrypt_payload(ciphertext, passphrase, material)
    payload = (
        _decompress_bounded(body)
        if manifest.get("compression") == "zlib"
        else body
    )

    if hashlib.sha256(payload).hexdigest() != manifest["payload_sha256"]:
        raise CorruptionError(
            "Decrypted payload failed its integrity hash; refusing to restore.", report
        )

    document, records, files = unpack_payload(payload)
    return ReadResult(manifest, document, records, files, report)


def _decompress_bounded(body: bytes) -> bytes:
    limit = setting("DBS_MAX_PAYLOAD_BYTES", DEFAULT_MAX_PAYLOAD_BYTES)
    decompressor = zlib.decompressobj()
    payload = decompressor.decompress(body, limit + 1)
    if len(payload) <= limit:
        payload += decompressor.flush()
    if len(payload) > limit or decompressor.unconsumed_tail:
        raise CorruptionError(
            f"Decompressed payload exceeds the {limit} byte limit "
            "(DBS_MAX_PAYLOAD_BYTES)."
        )
    return payload


def restore_backup(
    data: bytes,
    passphrase: str,
    *,
    using: str = "default",
    load_data: bool = True,
    write_files: bool = True,
    dry_run: bool = False,
    flush: bool = False,
) -> RestoreResult:
    """Restore database rows and files from container ``data``.

    Rows merge by primary key by default. ``flush`` clears the backed-up models
    first so the restore replaces rather than merges, and ``dry_run`` rehearses
    the whole load inside a transaction it rolls back, changing nothing.
    """
    result = read_payload(data, passphrase)
    out = RestoreResult(repair_report=result.repair_report)
    out.models = result.document.get("stats", {}).get("models", [])
    _warn_on_environment_drift(result.document, connections[using])

    backup_models = _backup_models(result.document, result.records)
    out.preexisting_models = [
        model._meta.label_lower
        for model in backup_models
        if model._base_manager.db_manager(using).exists()
    ]

    logger.info(
        "restore started: %d records, %d files",
        len(result.records),
        len(result.files),
    )

    if dry_run:
        _rehearse_load(
            result.records,
            out,
            backup_models,
            using=using,
            load_data=load_data,
            flush=flush,
        )
        if write_files:
            out.files_would_write = len(result.files)
        logger.info(
            "dry run complete: %d records would load, %d files would be written; nothing was changed",
            out.records_would_load,
            out.files_would_write,
        )
        return out

    if load_data:
        if flush:
            with transaction.atomic(using=using):
                out.records_flushed = _flush_existing_rows(backup_models, using)
                out.records_loaded = load_records(result.records, using=using)
            logger.info(
                "flush removed %d existing rows before the load",
                out.records_flushed,
            )
        else:
            if out.preexisting_models:
                logger.warning(
                    "target database already holds rows for %s; the restore will "
                    "merge by primary key (use flush to replace instead)",
                    ", ".join(out.preexisting_models),
                )
            out.records_loaded = load_records(result.records, using=using)
    if write_files:
        for entry, file_bytes in result.files:
            restore_file(entry, file_bytes)
            out.files_written += 1
    logger.info(
        "restore complete: %d records loaded, %d files written",
        out.records_loaded,
        out.files_written,
    )
    return out


def _rehearse_load(
    records: list,
    out: RestoreResult,
    backup_models: list,
    *,
    using: str,
    load_data: bool,
    flush: bool,
) -> None:
    if not load_data:
        return
    try:
        with transaction.atomic(using=using):
            if flush:
                out.records_flushed = _flush_existing_rows(backup_models, using)
            out.records_would_load = load_records(records, using=using)
            raise _DryRunRollback
    except _DryRunRollback:
        pass


def _backup_models(document: dict, records: list) -> list:
    labels = {record["model"] for record in records if record.get("model")}
    labels.update(
        entry["model"]
        for entry in document.get("stats", {}).get("models", [])
        if entry.get("model")
    )
    resolved = []
    for label in sorted(labels):
        try:
            resolved.append(apps.get_model(label))
        except LookupError:
            continue
    return resolved


def _flush_targets(models: list) -> list:
    targets = list(models)
    for model in models:
        for m2m in model._meta.local_many_to_many:
            through = m2m.remote_field.through
            if through._meta.auto_created and through not in targets:
                targets.append(through)
    return targets


def _flush_existing_rows(models: list, using: str) -> int:
    connection = connections[using]
    children_first = reversed(topological_order(_flush_targets(models)))
    deleted = 0
    with connection.cursor() as cursor:
        for model in children_first:
            table = connection.ops.quote_name(model._meta.db_table)
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            if count:
                cursor.execute(f"DELETE FROM {table}")
                deleted += count
    return deleted


def _warn_on_environment_drift(document: dict, connection) -> None:
    backup_django = document.get("django_version")
    if backup_django and backup_django != django.get_version():
        logger.warning(
            "backup was created with Django %s but Django %s is running",
            backup_django,
            django.get_version(),
        )
    recorded = document.get("migrations")
    if recorded is None:
        return
    target = migration_state(connection)
    backup_ahead = sorted(
        app for app, latest in recorded.items() if latest > target.get(app, "")
    )
    target_ahead = sorted(
        app for app, latest in target.items() if latest > recorded.get(app, "")
    )
    if backup_ahead:
        logger.warning(
            "migration drift for %s: the backup was taken on a newer schema than "
            "the target database; fields the target does not know are discarded on load",
            ", ".join(backup_ahead),
        )
    if target_ahead:
        logger.warning(
            "migration drift for %s: the target database schema is newer than "
            "the backup; fields added since the backup keep their defaults",
            ", ".join(target_ahead),
        )
