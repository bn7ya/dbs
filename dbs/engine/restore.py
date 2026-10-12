from __future__ import annotations

import hashlib
import logging
import zlib
from dataclasses import dataclass, field

from django.db import DatabaseError, IntegrityError, connections, transaction

from ..conf import setting
from ..container import repair_copies
from ..container.blocks import BlockPlan, RepairReport
from ..container.format import read_container
from ..crypto import decrypt_payload
from ..crypto.envelope import EnvelopeMaterial
from ..exceptions import ContainerError, CorruptionError, RestoreError
from ..files import check_file, restore_file
from ..introspect import topological_order
from ..notices import MERGED, RestoreWarning
from ..serialize import load_records, sentence
from .payload import unpack_payload
from .schema import (
    compare_schema,
    installed_model,
    migration_warnings,
    refuse_gaps,
    schema_warnings,
)

logger = logging.getLogger("dbs")

SUPPORTED_MANIFEST_VERSION = 1

DEFAULT_MAX_PAYLOAD_BYTES = 4 * 1024 ** 3


MERGE_HINT = (
    "The restore was merging into rows this database already held; if they are the same "
    "data under other ids, flush replaces them instead."
)


class _DryRunRollback(Exception):
    def __init__(self, loaded: int):
        super().__init__(loaded)
        self.loaded = loaded


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
    skipped_models: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

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
    allow_missing_models: bool = False,
) -> RestoreResult:
    """Restore database rows and files from container ``data``.

    Rows merge by primary key by default. ``flush`` clears the backed-up models
    first so the restore replaces rather than merges, and ``dry_run`` rehearses
    the whole load inside a transaction it rolls back, changing nothing.
    A backup holding models this project lacks is refused unless
    ``allow_missing_models`` leaves their rows and files out. Every other
    difference between the backup and this project is listed in ``warnings``.
    """
    result = read_payload(data, passphrase)
    out = RestoreResult(repair_report=result.repair_report)
    out.models = result.document.get("stats", {}).get("models", [])
    connection = connections[using]
    records = result.records if load_data else []
    files = result.files if write_files else []

    labels = _backup_labels(result.document, records) if load_data else set()
    gaps = compare_schema(records, files, labels, connection)
    refuse_gaps(gaps, allow_missing_models=allow_missing_models)
    out.skipped_models = gaps.missing_models
    records = [record for record in records if record.get("model") not in gaps.missing_rows]
    files = [(entry, content) for entry, content in files if not gaps.leaves_out(entry)]
    for entry, content in files:
        check_file(entry, content)

    backup_models = _backup_models(labels)
    if load_data:
        out.preexisting_models = [
            model._meta.label_lower
            for model in backup_models
            if model._base_manager.db_manager(using).exists()
        ]
    merging_into = set() if flush else set(out.preexisting_models)
    out.warnings.extend(migration_warnings(result.document, connection))
    out.warnings.extend(schema_warnings(gaps, merging_into))
    if merging_into:
        out.warnings.append(
            RestoreWarning(
                MERGED,
                "This database already holds rows for "
                + ", ".join(sorted(merging_into))
                + ", so the restore merges into them by id; flush replaces them instead.",
            )
        )

    logger.info("restore started: %d records, %d files", len(records), len(files))

    if dry_run:
        if load_data:
            out.records_would_load = _load(
                records, backup_models, out, using=using, flush=flush, rehearse=True
            )
        out.files_would_write = len(files)
        _log_warnings(out)
        logger.info(
            "dry run complete: %d records would load, %d files would be written; nothing was changed",
            out.records_would_load,
            out.files_would_write,
        )
        return out

    if load_data:
        out.records_loaded = _load(
            records, backup_models, out, using=using, flush=flush, rehearse=False
        )
        if flush:
            logger.info("flush removed %d existing rows before the load", out.records_flushed)
    _log_warnings(out)
    _write_files(files, out)
    logger.info(
        "restore complete: %d records loaded, %d files written",
        out.records_loaded,
        out.files_written,
    )
    return out


def _load(
    records: list,
    backup_models: list,
    out: RestoreResult,
    *,
    using: str,
    flush: bool,
    rehearse: bool,
) -> int:
    merging = bool(out.preexisting_models) and not flush
    try:
        with transaction.atomic(using=using):
            if flush:
                out.records_flushed = _flush_existing_rows(backup_models, using)
            loaded = load_records(records, using=using, warnings=out.warnings)
            if rehearse:
                raise _DryRunRollback(loaded)
    except _DryRunRollback as rollback:
        return rollback.loaded
    except (RestoreError, DatabaseError) as exc:
        raise RestoreError(_refusal(exc, merging)) from exc
    return loaded


def _refusal(exc: Exception, merging: bool) -> str:
    if isinstance(exc, RestoreError):
        message, cause = str(exc), exc.__cause__
    else:
        message, cause = "The database refused the restore: " + sentence(exc), exc
    if merging and isinstance(cause, IntegrityError):
        message += " " + MERGE_HINT
    return message + " Nothing was changed."


def _write_files(files: list, out: RestoreResult) -> None:
    for entry, content in files:
        try:
            restore_file(entry, content)
        except Exception as exc:
            restored = "The rows were restored, but " if out.records_loaded else ""
            raise RestoreError(
                f"{restored}{entry.name} could not be written: {sentence(exc)} "
                f"{out.files_written} of {len(files)} files were written."
            ) from exc
        out.files_written += 1


def _log_warnings(out: RestoreResult) -> None:
    for warning in out.warnings:
        logger.warning("%s", warning.message)


def _backup_labels(document: dict, records: list) -> set:
    labels = {record["model"] for record in records if record.get("model")}
    labels.update(
        entry["model"]
        for entry in document.get("stats", {}).get("models", [])
        if entry.get("model")
    )
    return labels


def _backup_models(labels) -> list:
    installed = (installed_model(label) for label in sorted(labels))
    return [model for model in installed if model is not None]


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
