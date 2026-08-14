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
from ..exceptions import CorruptionError
from ..files import collect_instance_files, collect_root_files
from ..io import write_atomic
from ..introspect import _label
from ..registry import backup_registry
from ..serialize import serialize_model
from .payload import pack_payload

logger = logging.getLogger("dbs")


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
) -> bytes:
    """Create a self-healing, encrypted backup and return the container bytes.

    If ``output`` is given the bytes are also written to that path.
    """
    registry = registry or backup_registry
    model_list = models or introspect.discover_models(registry)
    logger.info("backup started: %d models", len(model_list))

    records_all: list[dict] = []
    files_all: list = []
    stats_models: list[dict] = []
    skipped_files: list[str] = []
    seen_roots: set[str] = set()

    with transaction.atomic(using=using):
        for model in model_list:
            config = introspect.config_for(registry, model)
            excluded = introspect.excluded_fields(model, config)
            file_field_types = introspect.file_fields(model, config)

            records = serialize_model(model, config, excluded)
            records_all.extend(records)
            stats_models.append({"model": _label(model), "count": len(records)})

            if file_field_types:
                for instance in config.get_queryset(model).iterator():
                    files_all.extend(
                        collect_instance_files(instance, file_field_types, skipped_files)
                    )

            for root in config.file_roots or []:
                if root not in seen_roots:
                    seen_roots.add(root)
                    files_all.extend(collect_root_files(root, skipped_files))

        for root in getattr(settings, "DBS_FILE_ROOTS", []) or []:
            if root not in seen_roots:
                seen_roots.add(root)
                files_all.extend(collect_root_files(root, skipped_files))

    if skipped_files:
        logger.warning(
            "backup skipped %d unreadable source files: %s",
            len(skipped_files),
            ", ".join(skipped_files),
        )

    created = datetime.datetime.now(datetime.timezone.utc).isoformat()
    doc_meta = {
        "version": 1,
        "created": created,
        "django_version": django.get_version(),
        "migrations": migration_state(connections[using]),
        "stats": {
            "models": stats_models,
            "records": len(records_all),
            "files": len(files_all),
            "skipped_files": skipped_files,
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
        "stats": doc_meta["stats"],
    }
    flags = FLAG_ENCRYPTED | FLAG_FEC | (FLAG_COMPRESSED if compress else 0)
    container = write_container(manifest, encoded, encoded, flags=flags)

    if output:
        write_atomic(output, container)
        if verify:
            with open(output, "rb") as fh:
                _verify_after_write(fh.read(), passphrase, payload_sha)
    elif verify:
        _verify_after_write(container, passphrase, payload_sha)

    logger.info(
        "backup complete: %d records, %d files, %d bytes",
        len(records_all),
        len(files_all),
        len(container),
    )
    return container


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
