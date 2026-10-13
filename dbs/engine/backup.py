from __future__ import annotations

import datetime
import hashlib
import logging
import zlib

import django
from django.conf import settings
from django.db import connections, transaction
from django.db.migrations.recorder import MigrationRecorder

from .. import introspect
from ..container import DEFAULT_BLOCK_SIZE, DEFAULT_NSYM, encode_copy, write_container
from ..container.format import FLAG_COMPRESSED, FLAG_ENCRYPTED, FLAG_FEC
from ..crypto import encrypt_payload
from ..crypto.kdf import KDFParams
from ..exceptions import BackupError, CorruptionError, MissingSourceFiles
from ..files import collect_instance_files, collect_root_files
from ..io import refuse_existing, write_new_file
from ..introspect import _label
from ..registry import backup_registry
from ..serialize import serialize_model
from .payload import pack_payload

logger = logging.getLogger("dbs")

NAMED_MISSING_FILES = 20


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

    Rows are read from the ``using`` database. If ``output`` is given the bytes
    are also written to that path, which must not exist yet: the file is
    written and verified beside it, then moved into place. A source file that
    is missing or unreadable stops the backup unless ``allow_missing_files``
    is true; the paths left out are then listed in the backup's metadata and
    appended to ``skipped_files`` when a list is passed.
    """
    if output:
        _refuse_existing_output(output)
    registry = registry or backup_registry
    selection = introspect.backup_plan(registry, models)
    logger.info("backup started: %d models", len(selection))

    records_all: list[dict] = []
    files_all: list = []
    stats_models: list[dict] = []
    skipped: list[str] = []
    seen_roots: set[str] = set()

    carried = frozenset(model for model, _config in selection)
    connection = connections[using]
    pin_snapshot = connection.vendor == "postgresql" and not connection.in_atomic_block

    with transaction.atomic(using=using):
        if pin_snapshot:
            read_from_one_snapshot(connection)
        for model, config in selection:
            excluded = introspect.excluded_fields(model, config)
            file_field_types = introspect.file_fields(model, config)

            records = serialize_model(model, config, excluded, carried, using=using)
            records_all.extend(records)
            stats_models.append({"model": _label(model), "count": len(records)})

            if file_field_types:
                for instance in config.get_queryset(model).using(using).iterator():
                    files_all.extend(
                        collect_instance_files(instance, file_field_types, skipped)
                    )

            for root in config.file_roots or []:
                if root not in seen_roots:
                    seen_roots.add(root)
                    files_all.extend(collect_root_files(root, skipped))

        for root in getattr(settings, "DBS_FILE_ROOTS", []) or []:
            if root not in seen_roots:
                seen_roots.add(root)
                files_all.extend(collect_root_files(root, skipped))

    if skipped_files is not None:
        skipped_files.extend(skipped)
    if skipped and not allow_missing_files:
        raise MissingSourceFiles(_missing_files_message(skipped), skipped)
    if skipped:
        logger.warning(
            "backup left out %d source files that could not be read: %s",
            len(skipped),
            ", ".join(skipped),
        )

    created = datetime.datetime.now(datetime.timezone.utc).isoformat()
    doc_meta = {
        "version": 1,
        "created": created,
        "django_version": django.get_version(),
        "migrations": migration_state(connection),
        "order": [_label(model) for model, _config in selection],
        "stats": {
            "models": stats_models,
            "records": len(records_all),
            "files": len(files_all),
            "skipped_files": skipped,
        },
    }

    payload = pack_payload(doc_meta, records_all, files_all)
    payload_sha = hashlib.sha256(payload).hexdigest()

    body = zlib.compress(payload, 6) if compress else payload
    kdf_params = kdf_params or _kdf_params_from_settings()
    ciphertext, material = encrypt_payload(body, passphrase, kdf_params=kdf_params)
    encoded, plan = encode_copy(ciphertext, block_size=block_size, nsym=nsym)

    manifest = {
        "format": "DBS",
        "version": 1,
        "created": created,
        "compression": "zlib" if compress else None,
        "payload_sha256": payload_sha,
        "copy_len": plan.copy_len,
        "blocks": plan.to_dict(),
        "crypto": material.to_dict(),
    }
    flags = FLAG_ENCRYPTED | FLAG_FEC | (FLAG_COMPRESSED if compress else 0)
    container = write_container(manifest, encoded, encoded, flags=flags)

    if output:
        _write_output(output, container, passphrase, payload_sha if verify else None)
    elif verify:
        _verify_after_write(container, passphrase, payload_sha)

    logger.info(
        "backup complete: %d records, %d files, %d bytes",
        len(records_all),
        len(files_all),
        len(container),
    )
    return container


def _existing_output_error(output: str) -> BackupError:
    return BackupError(
        f"{output} already exists. DBS never replaces a backup file; choose a new name."
    )


def _refuse_existing_output(output: str) -> None:
    try:
        refuse_existing(output)
    except FileExistsError:
        raise _existing_output_error(output) from None


def _write_output(output: str, container: bytes, passphrase: str, payload_sha) -> None:
    def verify_partial(partial: str) -> None:
        with open(partial, "rb") as fh:
            _verify_after_write(fh.read(), passphrase, payload_sha)

    try:
        write_new_file(output, container, verify_partial if payload_sha else None)
    except FileExistsError:
        raise _existing_output_error(output) from None


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


def _verify_after_write(container: bytes, passphrase: str, payload_sha: str) -> None:
    from .restore import read_payload

    result = read_payload(container, passphrase)
    if result.manifest["payload_sha256"] != payload_sha:
        raise CorruptionError(
            "verify-after-write: the freshly written container does not match its source."
        )
