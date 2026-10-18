from __future__ import annotations

import hashlib
import logging
import zlib
from contextlib import contextmanager
from dataclasses import dataclass, field

import django
from django.apps import apps
from django.db import connections, transaction

from ..conf import setting
from ..container import StreamReader, read_format_version, repair_copies
from ..container.blocks import BlockPlan, RepairReport
from ..container.format import STREAM_FORMAT_VERSION, read_container
from ..crypto import decrypt_payload
from ..crypto.envelope import EnvelopeMaterial
from ..exceptions import ContainerError, CorruptionError, RestoreError
from ..files import StagedFiles, plan_entries, plan_restore, refusal_message
from ..introspect import backup_plan, excluded_fields, topological_order
from ..registry import ModelBackup, backup_registry
from ..serialize import NaturalKeyResolver, RowLoader, resolve_natural_keys, save_records
from .backup import migration_state
from .frames import KNOWN_FLAGS, PayloadReader
from .inputs import opened, stream_source, whole
from .payload import unpack_payload
from .pipeline import decoding

logger = logging.getLogger("dbs")

SUPPORTED_MANIFEST_VERSION = 1

DEFAULT_MAX_PAYLOAD_BYTES = 4 * 1024 ** 3

FLUSH_BATCH = 500


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
    files_refused: list = field(default_factory=list)

    @property
    def healed(self) -> bool:
        return bool(self.repair_report and self.repair_report.healed)


def _read_v1_payload(data: bytes, passphrase: str) -> ReadResult:
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


def backup_files(data, passphrase: str):
    with opened(data) as handle:
        if read_format_version(handle) != STREAM_FORMAT_VERSION:
            for entry, content in _read_v1_payload(whole(handle), passphrase).files:
                yield entry, iter((content,))
            return
        with open_stream(handle, passphrase) as (_reader, payload):
            payload.read_header()
            payload.read_manifest()
            for stream in payload.files():
                yield stream.entry, _whole_file(stream)
            _finish_stream(payload, RestoreResult(), records=False)


def _whole_file(stream):
    yield from stream.chunks()
    if stream.skipped:
        raise RestoreError(
            f"{stream.entry.name} was left out when the backup was taken ({stream.skipped})."
        )


def open_reader(handle, passphrase: str | None):
    source = stream_source(handle)
    reader = StreamReader(source, passphrase)
    unknown = reader.flags & ~KNOWN_FLAGS
    if unknown:
        raise ContainerError(
            f"This backup sets payload flags {unknown:#x} that this version of DBS "
            "does not know; it was written by a newer DBS."
        )
    return reader, source


@contextmanager
def read_frames(reader: StreamReader, source, *, check_spares: bool = False):
    with decoding(reader, source, check_spares=check_spares) as pieces:
        yield PayloadReader(pieces)
    if reader.report.healed:
        logger.warning("corruption detected and healed: %s", reader.report.summary())


@contextmanager
def open_stream(handle, passphrase: str, *, check_spares: bool = False):
    reader, source = open_reader(handle, passphrase)
    with read_frames(reader, source, check_spares=check_spares) as payload:
        yield reader, payload


def _decompress_bounded(body: bytes) -> bytes:
    limit = setting("DBS_MAX_PAYLOAD_BYTES", DEFAULT_MAX_PAYLOAD_BYTES)
    decompressor = zlib.decompressobj()
    payload = decompressor.decompress(body, limit + 1)
    if len(payload) <= limit:
        payload += decompressor.flush()
    if len(payload) > limit or decompressor.unconsumed_tail:
        raise CorruptionError(
            f"Decompressed payload exceeds the {limit} byte limit that format 1 "
            "backups are read within (DBS_MAX_PAYLOAD_BYTES)."
        )
    return payload


def restore_backup(
    data,
    passphrase: str,
    *,
    using: str = "default",
    load_data: bool = True,
    write_files: bool = True,
    dry_run: bool = False,
    flush: bool = False,
    registry=None,
) -> RestoreResult:
    """Restore database rows and files from the backup in ``data``.

    ``data`` is the container's bytes, a path to it, or a binary file object
    that can be read and sought. A format 2 backup streams: rows load in
    batches and files are staged as they arrive, so memory stays bounded. A
    format 1 backup is read whole, within ``DBS_MAX_PAYLOAD_BYTES``.
    Rows load in the order the backup recorded, parents before children, and
    merge by primary key by default: an existing row only takes the fields the
    backup carries. ``flush`` first deletes the rows the backup covers so the
    restore replaces rather than merges. Every file target is checked before
    any row loads; files are staged beside their targets and moved into place
    when the rows commit. ``dry_run`` runs the same checks, lists refused files
    in ``files_refused`` and rehearses the load in a transaction it rolls back,
    changing nothing.
    """
    registry = registry or backup_registry
    options = {
        "using": using,
        "load_data": load_data,
        "write_files": write_files,
        "dry_run": dry_run,
        "flush": flush,
        "registry": registry,
    }
    with opened(data) as handle:
        if read_format_version(handle) == STREAM_FORMAT_VERSION:
            return _restore_stream(handle, passphrase, **options)
        return _restore_v1(whole(handle), passphrase, **options)


def _restore_v1(
    data: bytes,
    passphrase: str,
    *,
    using: str,
    load_data: bool,
    write_files: bool,
    dry_run: bool,
    flush: bool,
    registry,
) -> RestoreResult:
    result = _read_v1_payload(data, passphrase)
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

    placements = plan_restore(result.files, registry=registry) if write_files else []
    out.files_refused = [placement.problem for placement in placements if placement.problem]
    records = _point_rows_at_moved_files(
        ordered_records(result.document, result.records), placements
    )

    if dry_run:
        out.files_would_write = len(placements) - len(out.files_refused)
        _rehearse_load(
            records,
            out,
            backup_models,
            using=using,
            load_data=load_data,
            flush=flush,
            registry=registry,
        )
        logger.info(
            "dry run complete: %d records would load, %d files would be written, "
            "%d files would be refused; nothing was changed",
            out.records_would_load,
            out.files_would_write,
            len(out.files_refused),
        )
        return out

    if out.files_refused:
        raise RestoreError(refusal_message(out.files_refused))

    staged = StagedFiles()
    staged.stage_all(placements)
    try:
        if load_data:
            _load(records, out, backup_models, staged, using=using, flush=flush, registry=registry)
        else:
            _publish(staged, out)
    except BaseException:
        staged.discard()
        raise
    logger.info(
        "restore complete: %d records loaded, %d files written",
        out.records_loaded,
        out.files_written,
    )
    return out


def _restore_stream(
    handle,
    passphrase: str,
    *,
    using: str,
    load_data: bool,
    write_files: bool,
    dry_run: bool,
    flush: bool,
    registry,
) -> RestoreResult:
    out = RestoreResult()
    with open_stream(handle, passphrase) as (reader, payload):
        header = payload.read_header()
        _warn_on_environment_drift(header, connections[using])
        backup_models = _models_named(header["order"])
        out.preexisting_models = [
            model._meta.label_lower
            for model in backup_models
            if model._base_manager.db_manager(using).exists()
        ]
        entries = payload.read_manifest()
        logger.info("restore started: %d files", len(entries))
        placements = plan_entries(entries, registry=registry) if write_files else []
        out.files_refused = [placement.problem for placement in placements if placement.problem]
        rows = _StreamedRows(payload, header["order"], placements, using)

        if dry_run:
            out.files_would_write = len(placements) - len(out.files_refused)
            _drain_files(payload)
            if load_data:
                _rehearse_stream(rows, out, backup_models, using=using, flush=flush, registry=registry)
            else:
                _finish_stream(payload, out, records=False)
            out.repair_report = reader.report
            logger.info(
                "dry run complete: %d records would load, %d files would be written, "
                "%d files would be refused; nothing was changed",
                out.records_would_load,
                out.files_would_write,
                len(out.files_refused),
            )
            return out

        if out.files_refused:
            raise RestoreError(refusal_message(out.files_refused))

        staged = StagedFiles()
        try:
            _stage_files(payload, placements, staged)
            if load_data:
                _load_stream(rows, out, backup_models, staged, using=using, flush=flush, registry=registry)
            else:
                _finish_stream(payload, out, records=False)
                _publish(staged, out)
        except BaseException:
            staged.discard()
            raise
    out.repair_report = reader.report
    logger.info(
        "restore complete: %d records loaded, %d files written",
        out.records_loaded,
        out.files_written,
    )
    return out


class _StreamedRows:
    def __init__(self, payload: PayloadReader, order: list, placements: list, using: str):
        self.payload = payload
        self.moved = _moved_files(placements)
        self.resolver = NaturalKeyResolver([], using, carried=order)
        self.loader = RowLoader(using)

    def load(self) -> None:
        with self.loader.connection.constraint_checks_disabled():
            for batch in self.payload.record_batches():
                pointed = _point_rows(batch, self.moved)
                self.loader.save([self.resolver.record(record) for record in pointed])

    def finish(self, out: RestoreResult, *, adjust_sequences: bool) -> int:
        _finish_stream(self.payload, out, records=True)
        self.resolver.report()
        return self.loader.finish(adjust_sequences=adjust_sequences)


def _finish_stream(payload: PayloadReader, out: RestoreResult, *, records: bool) -> None:
    if not records:
        for _batch in payload.record_batches(parse=False):
            pass
    payload.read_trailer()
    payload.finish()
    out.models = payload.stats.get("models", [])


def _drain_files(payload: PayloadReader) -> None:
    for stream in payload.files():
        stream.drain()


def _stage_files(payload: PayloadReader, placements: list, staged: StagedFiles) -> None:
    for stream in payload.files():
        if not placements:
            stream.drain()
            continue
        staging = staged.begin(placements[stream.index])
        try:
            for chunk in stream.chunks():
                staging.write(chunk)
        except BaseException:
            staging.abort()
            raise
        if stream.skipped:
            staging.abort()
            continue
        staging.finish()


def _load_stream(rows: _StreamedRows, out, backup_models, staged, *, using, flush, registry) -> None:
    if not flush and out.preexisting_models:
        logger.warning(
            "target database already holds rows for %s; the restore will "
            "merge by primary key (use flush to replace instead)",
            ", ".join(out.preexisting_models),
        )
    with transaction.atomic(using=using):
        if flush:
            out.records_flushed = _flush_existing_rows(backup_models, using, registry)
        rows.load()
        out.records_loaded = rows.finish(out, adjust_sequences=True)
        transaction.on_commit(lambda: _publish(staged, out), using=using)
    if flush:
        logger.info("flush removed %d existing rows before the load", out.records_flushed)


def _rehearse_stream(rows: _StreamedRows, out, backup_models, *, using, flush, registry) -> None:
    try:
        with transaction.atomic(using=using):
            if flush:
                out.records_flushed = _flush_existing_rows(backup_models, using, registry)
            rows.load()
            out.records_would_load = rows.finish(out, adjust_sequences=False)
            raise _DryRunRollback
    except _DryRunRollback:
        pass


def _models_named(labels) -> list:
    resolved = []
    for label in sorted(set(labels)):
        try:
            resolved.append(apps.get_model(label))
        except (LookupError, ValueError):
            continue
    return resolved


def _load(records, out, backup_models, staged, *, using, flush, registry) -> None:
    prepared = resolve_natural_keys(records, using) if records else []
    if not flush and out.preexisting_models:
        logger.warning(
            "target database already holds rows for %s; the restore will "
            "merge by primary key (use flush to replace instead)",
            ", ".join(out.preexisting_models),
        )
    with transaction.atomic(using=using):
        if flush:
            out.records_flushed = _flush_existing_rows(backup_models, using, registry)
        out.records_loaded = save_records(prepared, using=using)
        transaction.on_commit(lambda: _publish(staged, out), using=using)
    if flush:
        logger.info("flush removed %d existing rows before the load", out.records_flushed)


def _publish(staged: StagedFiles, out: RestoreResult) -> None:
    try:
        staged.publish()
    finally:
        out.files_written = staged.published


def _rehearse_load(
    records: list,
    out: RestoreResult,
    backup_models: list,
    *,
    using: str,
    load_data: bool,
    flush: bool,
    registry,
) -> None:
    if not load_data:
        return
    prepared = resolve_natural_keys(records, using) if records else []
    try:
        with transaction.atomic(using=using):
            if flush:
                out.records_flushed = _flush_existing_rows(backup_models, using, registry)
            out.records_would_load = save_records(prepared, using=using, adjust_sequences=False)
            raise _DryRunRollback
    except _DryRunRollback:
        pass


def ordered_records(document: dict, records: list) -> list:
    order = document.get("order") or _target_order(records)
    rank = {label: position for position, label in enumerate(order)}
    return sorted(records, key=lambda record: rank.get(record.get("model"), len(rank)))


def _target_order(records: list) -> list:
    models = []
    for label in dict.fromkeys(record.get("model") for record in records):
        try:
            models.append(apps.get_model(label))
        except (LookupError, TypeError, ValueError):
            continue
    return [model._meta.label_lower for model in topological_order(models)]


def _moved_files(placements: list) -> dict:
    return {
        (placement.entry.model, str(placement.entry.pk), placement.entry.field): placement.moved_to
        for placement in placements
        if placement.moved_to and not placement.problem
    }


def _point_rows(records: list, moved: dict) -> list:
    if not moved:
        return records
    pointed = []
    for record in records:
        fields = record.get("fields", {})
        changes = {
            name: moved[(record.get("model"), str(record.get("pk")), name)]
            for name in fields
            if (record.get("model"), str(record.get("pk")), name) in moved
        }
        pointed.append({**record, "fields": {**fields, **changes}} if changes else record)
    return pointed


def _point_rows_at_moved_files(records: list, placements: list) -> list:
    return _point_rows(records, _moved_files(placements))


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


def _covers_whole_table(config) -> bool:
    return type(config).get_queryset is ModelBackup.get_queryset


def _flush_scopes(models: list, using: str, registry) -> dict:
    configs = dict(backup_plan(registry))
    scopes: dict = {}
    for model in models:
        config = configs.get(model) or ModelBackup()
        keys = None
        if not _covers_whole_table(config):
            keys = list(config.get_queryset(model).using(using).values_list("pk", flat=True))
        scopes[model] = None if keys is None else ("pk", keys)
        skipped = excluded_fields(model, config)
        for m2m in model._meta.local_many_to_many:
            through = m2m.remote_field.through
            if not through._meta.auto_created or m2m.name in skipped:
                continue
            scopes[through] = None if keys is None else (m2m.m2m_field_name(), keys)
    return scopes


def _flush_existing_rows(models: list, using: str, registry=None) -> int:
    scopes = _flush_scopes(models, using, registry or backup_registry)
    connection = connections[using]
    deleted = 0
    with connection.constraint_checks_disabled():
        for model in reversed(topological_order(list(scopes))):
            scope = scopes[model]
            if scope is None:
                deleted += _delete_table(connection, model)
            else:
                deleted += _delete_selected(model, *scope, using=using)
    return deleted


def _delete_table(connection, model) -> int:
    table = connection.ops.quote_name(model._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        if count:
            cursor.execute(f"DELETE FROM {table}")
    return count


def _delete_selected(model, column: str, keys: list, *, using: str) -> int:
    manager = model._base_manager.using(using)
    deleted = 0
    for start in range(0, len(keys), FLUSH_BATCH):
        batch = keys[start : start + FLUSH_BATCH]
        deleted += manager.filter(**{f"{column}__in": batch})._raw_delete(using)
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
            "the backup; fields added since the backup keep their defaults on new "
            "rows and their current values on existing ones",
            ", ".join(target_ahead),
        )
