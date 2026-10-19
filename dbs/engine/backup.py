from __future__ import annotations

import datetime
import hashlib
import io
import logging
import os
from dataclasses import dataclass, field

import django
from django.conf import settings
from django.db import connections, transaction
from django.db.migrations.recorder import MigrationRecorder

from .. import introspect
from ..container import (
    DEFAULT_BLOCK_SIZE,
    DEFAULT_INTERLEAVE,
    DEFAULT_NSYM,
    FORMAT_VERSION,
    StreamReader,
)
from ..container.stream import MAX_WINDOW_BYTES, StreamLayout, layout_problem
from ..crypto.kdf import KDFParams
from ..exceptions import BackupError, CorruptionError, MissingSourceFiles
from ..files import SkippedFile, list_instance_files, list_root_files, read_chunks
from ..introspect import _label
from ..io import create_new_file
from ..registry import backup_registry
from ..serialize import Pages, serialize_batches
from . import frames
from .inputs import is_path, opened, stream_source
from .pipeline import decoding, encoding

logger = logging.getLogger("dbs")

NAMED_MISSING_FILES = 20

LISTED_ROWS = 2000

SNAPSHOT_VENDORS = ("postgresql", "mysql")


@dataclass
class BackupSummary:
    """What a written backup holds and how much damage it can heal.

    ``bytes_written`` and ``sha256`` describe the container as written;
    ``records``, ``files``, ``skipped_files`` and ``models`` what it carries;
    ``blocks``, ``block_size``, ``nsym``, ``interleave``,
    ``correctable_bytes_per_codeword`` and ``burst_tolerance_bytes`` its repair
    margins. ``verified`` is true when the written bytes were read back.
    """

    bytes_written: int
    sha256: str
    records: int
    files: int
    skipped_files: list = field(default_factory=list)
    models: list = field(default_factory=list)
    path: str | None = None
    verified: bool = False
    compressed: bool = True
    payload_bytes: int = 0
    payload_sha256: str = ""
    format_version: int = FORMAT_VERSION
    blocks: int = 0
    block_size: int = 0
    nsym: int = 0
    interleave: int = 0
    correctable_bytes_per_codeword: int = 0
    burst_tolerance_bytes: int = 0


def write_backup(
    output,
    passphrase: str,
    *,
    registry=None,
    models: list | None = None,
    using: str = "default",
    block_size: int = DEFAULT_BLOCK_SIZE,
    nsym: int = DEFAULT_NSYM,
    interleave: int | None = None,
    kdf_params: KDFParams | None = None,
    compress: bool = True,
    verify: bool = True,
    allow_missing_files: bool = False,
    skipped_files: list | None = None,
    workers: int | None = None,
) -> BackupSummary:
    """Stream a self-healing, encrypted backup to ``output`` and return a summary.

    ``output`` is a path that must not exist yet, or a binary file object such
    as an open file, ``sys.stdout.buffer`` or a socket's file. Rows are read in
    batches from the ``using`` database and files in chunks while other threads
    compress, encrypt, add Reed-Solomon parity and write, so memory stays
    bounded however large the backup grows. A path is written and verified
    beside its final name, then moved into place; a file object that can be
    read and sought is verified where it was written. A source file that is
    missing or unreadable stops the backup unless ``allow_missing_files`` is
    true; the paths left out are then listed in the backup and appended to
    ``skipped_files`` when a list is passed.
    """
    options = {
        "registry": registry,
        "models": models,
        "using": using,
        "writer_options": _writer_options(block_size, nsym, interleave, kdf_params, workers),
        "compress": compress,
        "allow_missing_files": allow_missing_files,
        "skipped_files": skipped_files,
    }
    if is_path(output):
        return _write_path(os.fspath(output), passphrase, verify, options)
    return _write_stream(output, passphrase, verify, options)


def create_backup(
    passphrase: str,
    *,
    registry=None,
    models: list | None = None,
    using: str = "default",
    block_size: int = DEFAULT_BLOCK_SIZE,
    nsym: int = DEFAULT_NSYM,
    kdf_params: KDFParams | None = None,
    compress: bool = True,
    verify: bool = True,
    output: str | None = None,
    allow_missing_files: bool = False,
    skipped_files: list | None = None,
) -> bytes:
    """Create a self-healing, encrypted backup and return the container bytes.

    The whole container is returned in memory, so this suits small backups;
    :func:`write_backup` streams one of any size. If ``output`` is given the
    bytes are also written to that path, which must not exist yet: the file is
    written and verified beside it, then moved into place. Rows are read from
    the ``using`` database. A source file that is missing or unreadable stops
    the backup unless ``allow_missing_files`` is true; the paths left out are
    then listed in the backup's metadata and appended to ``skipped_files``
    when a list is passed.
    """
    options = {
        "registry": registry,
        "models": models,
        "using": using,
        "block_size": block_size,
        "nsym": nsym,
        "kdf_params": kdf_params,
        "compress": compress,
        "verify": verify,
        "allow_missing_files": allow_missing_files,
        "skipped_files": skipped_files,
    }
    if output:
        write_backup(output, passphrase, **options)
        with open(output, "rb") as fh:
            return fh.read()
    buffer = io.BytesIO()
    write_backup(buffer, passphrase, **options)
    return buffer.getvalue()


def _writer_options(block_size, nsym, interleave, kdf_params, workers) -> dict:
    if interleave is None:
        interleave = _fitting_interleave(block_size, nsym)
    problem = layout_problem(block_size, nsym, interleave)
    if problem:
        raise BackupError(f"Cannot lay out the backup: {problem}")
    return {
        "block_size": block_size,
        "nsym": nsym,
        "interleave": interleave,
        "kdf_params": kdf_params or _kdf_params_from_settings(),
        "workers": workers,
    }


def _fitting_interleave(block_size, nsym) -> int:
    try:
        slot_size = StreamLayout(block_size, nsym, 1).slot_size
    except (TypeError, ValueError):
        return DEFAULT_INTERLEAVE
    return max(1, min(DEFAULT_INTERLEAVE, MAX_WINDOW_BYTES // max(slot_size, 1)))


def _write_path(output: str, passphrase: str, verify: bool, options: dict) -> BackupSummary:
    written: dict = {}

    def verify_partial(partial: str) -> None:
        _verify_after_write(partial, passphrase, written["summary"].payload_sha256)

    try:
        with create_new_file(output, verify_partial if verify else None) as fh:
            written["summary"] = _stream_backup(fh, passphrase, **options)
    except FileExistsError:
        raise _existing_output_error(output) from None
    summary = written["summary"]
    summary.path = output
    summary.verified = verify
    return summary


def _write_stream(output, passphrase: str, verify: bool, options: dict) -> BackupSummary:
    start = _verifiable_start(output) if verify else None
    summary = _stream_backup(output, passphrase, **options)
    if start is not None:
        end = output.tell()
        output.seek(start)
        try:
            _verify_after_write(output, passphrase, summary.payload_sha256)
        finally:
            output.seek(end)
        summary.verified = True
    return summary


def _verifiable_start(output):
    try:
        if output.seekable() and output.readable():
            return output.tell()
    except (AttributeError, OSError, ValueError):
        pass
    return None


def _stream_backup(
    output,
    passphrase: str,
    *,
    registry,
    models,
    using: str,
    writer_options: dict,
    compress: bool,
    allow_missing_files: bool,
    skipped_files: list | None,
) -> BackupSummary:
    selection = introspect.backup_plan(registry or backup_registry, models)
    logger.info("backup started: %d models", len(selection))
    skipped: list[str] = []
    try:
        with encoding(output, passphrase, compress=compress, **writer_options) as stream:
            stats = _produce(
                stream.write,
                selection,
                using=using,
                skipped=skipped,
                allow_missing_files=allow_missing_files,
            )
    finally:
        if skipped_files is not None:
            skipped_files.extend(skipped)
    container = stream.container
    logger.info(
        "backup complete: %d records, %d files, %d bytes",
        stats["records"],
        stats["files"],
        container.container_bytes,
    )
    return BackupSummary(
        bytes_written=container.container_bytes,
        sha256=container.sha256,
        records=stats["records"],
        files=stats["files"],
        skipped_files=list(skipped),
        models=stats["models"],
        compressed=compress,
        payload_bytes=stream.payload_bytes,
        payload_sha256=stream.digest.hexdigest(),
        blocks=container.blocks,
        block_size=container.block_size,
        nsym=container.nsym,
        interleave=container.interleave,
        correctable_bytes_per_codeword=container.correctable_bytes_per_codeword,
        burst_tolerance_bytes=container.burst_tolerance_bytes,
    )


def _produce(emit, selection, *, using: str, skipped: list, allow_missing_files: bool) -> dict:
    connection = connections[using]
    pin_snapshot = connection.vendor in SNAPSHOT_VENDORS and not connection.in_atomic_block
    with transaction.atomic(using=using):
        if pin_snapshot:
            read_from_one_snapshot(connection)
        emit(frames.PAYLOAD_MAGIC)
        emit(
            frames.json_frame(
                frames.HEADER,
                {
                    "version": frames.PAYLOAD_VERSION,
                    "created": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "django_version": django.get_version(),
                    "migrations": migration_state(connection),
                    "order": [_label(model) for model, _config in selection],
                },
            )
        )
        sources = _listed_files(selection, using, skipped)
        if skipped and not allow_missing_files:
            raise MissingSourceFiles(_missing_files_message(skipped), skipped)
        if len(sources) > frames.MAX_FILES:
            raise BackupError(f"A backup holds at most {frames.MAX_FILES} files.")
        for start in range(0, len(sources), frames.MANIFEST_BATCH):
            batch = sources[start : start + frames.MANIFEST_BATCH]
            emit(
                frames.json_frame(
                    frames.MANIFEST, [frames.manifest_item(source.entry) for source in batch]
                )
            )
        files = _emit_files(emit, sources, skipped, allow_missing_files)
        stats_models, records = _emit_records(emit, selection, using)
    if skipped:
        logger.warning(
            "backup left out %d source files that could not be read: %s",
            len(skipped),
            ", ".join(skipped),
        )
    stats = {
        "models": stats_models,
        "records": records,
        "files": files,
        "skipped_files": list(skipped),
    }
    emit(frames.json_frame(frames.TRAILER, {"stats": stats}))
    return stats


def _listed_files(selection, using: str, skipped: list) -> list:
    sources: list = []
    seen_roots: set[str] = set()
    for model, config in selection:
        file_field_types = introspect.file_fields(model, config)
        if file_field_types:
            queryset = config.get_queryset(model).using(using).only(*file_field_types)
            for chunk in Pages(queryset, LISTED_ROWS, adaptive=False):
                for instance in chunk:
                    sources.extend(list_instance_files(instance, file_field_types, skipped))
        for root in config.file_roots or []:
            if root not in seen_roots:
                seen_roots.add(root)
                sources.extend(list_root_files(root, skipped))
    for root in getattr(settings, "DBS_FILE_ROOTS", []) or []:
        if root not in seen_roots:
            seen_roots.add(root)
            sources.extend(list_root_files(root, skipped))
    return sources


def _emit_files(emit, sources: list, skipped: list, allow_missing_files: bool) -> int:
    written = 0
    for index, source in enumerate(sources):
        digest = hashlib.sha256()
        size = 0
        try:
            for chunk in read_chunks(source, frames.FILE_CHUNK_BYTES):
                digest.update(chunk)
                size += len(chunk)
                emit(frames.file_data_frame(index, chunk))
        except SkippedFile as reason:
            skipped.append(f"{source.described} ({reason})")
            if not allow_missing_files:
                raise MissingSourceFiles(_missing_files_message(skipped), skipped) from None
            emit(frames.file_end_frame(index, skipped=str(reason)))
            continue
        emit(frames.file_end_frame(index, size=size, sha256=digest.hexdigest()))
        written += 1
    return written


def _emit_records(emit, selection, using: str) -> tuple[list, int]:
    carried = frozenset(model for model, _config in selection)
    stats_models = []
    total = 0
    for model, config in selection:
        excluded = introspect.excluded_fields(model, config)
        count = 0
        for pieces, rows in serialize_batches(
            model, config, excluded, carried, using=using, limit=frames.MAX_FRAME_BYTES
        ):
            for piece in frames.frame_parts(frames.RECORDS, pieces):
                emit(piece)
            count += rows
        stats_models.append({"model": _label(model), "count": count})
        total += count
    return stats_models, total


def _existing_output_error(output: str) -> BackupError:
    return BackupError(
        f"{output} already exists. DBS never replaces a backup file; choose a new name."
    )


def _missing_files_message(skipped: list[str]) -> str:
    named = "; ".join(skipped[:NAMED_MISSING_FILES])
    if len(skipped) > NAMED_MISSING_FILES:
        named += f"; and {len(skipped) - NAMED_MISSING_FILES} more"
    return (
        f"{len(skipped)} source file(s) could not be read, so no backup was written: "
        f"{named}. Put them back, or pass allow_missing_files=True "
        "(--allow-missing-files) to back up without them."
    )


def read_from_one_snapshot(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        if connection.vendor == "mysql":
            cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")


def migration_state(connection) -> dict[str, str]:
    recorder = MigrationRecorder(connection)
    if not recorder.has_table():
        return {}
    state: dict[str, str] = {}
    for app, name in sorted(recorder.applied_migrations()):
        state[app] = name
    return state


def _kdf_params_from_settings() -> KDFParams:
    return KDFParams(
        time_cost=int(getattr(settings, "DBS_KDF_TIME_COST", KDFParams.time_cost)),
        memory_cost=int(
            getattr(settings, "DBS_KDF_MEMORY_COST", KDFParams.memory_cost)
        ),
        parallelism=int(
            getattr(settings, "DBS_KDF_PARALLELISM", KDFParams.parallelism)
        ),
    )


def verify_written(source, passphrase: str, summary: BackupSummary) -> None:
    _verify_after_write(source, passphrase, summary.payload_sha256)


def _verify_after_write(source, passphrase: str, payload_sha256: str) -> None:
    digest = hashlib.sha256()
    with opened(source) as handle:
        reader_source = stream_source(handle)
        reader = StreamReader(reader_source, passphrase)
        with decoding(reader, reader_source, check_spares=True) as pieces:
            for piece in pieces:
                digest.update(piece)
    report = reader.report
    if not report.ok or report.healed:
        raise CorruptionError(
            "verify-after-write: the freshly written container needed repair: "
            + report.summary(),
            report,
        )
    if digest.hexdigest() != payload_sha256:
        raise CorruptionError(
            "verify-after-write: the freshly written container does not match its source."
        )
