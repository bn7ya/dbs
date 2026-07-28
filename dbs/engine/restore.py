from __future__ import annotations

import hashlib
import logging
import zlib
from dataclasses import dataclass, field

from ..conf import setting
from ..container import repair_copies
from ..container.blocks import BlockPlan, RepairReport
from ..container.format import read_container
from ..crypto import decrypt_payload
from ..crypto.envelope import EnvelopeMaterial
from ..exceptions import ContainerError, CorruptionError
from ..files import restore_file
from ..serialize import load_records
from .payload import unpack_payload

logger = logging.getLogger("dbs")

SUPPORTED_MANIFEST_VERSION = 1

DEFAULT_MAX_PAYLOAD_BYTES = 4 * 1024 ** 3


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
) -> RestoreResult:
    """Restore database rows and files from container ``data``."""
    result = read_payload(data, passphrase)
    out = RestoreResult(repair_report=result.repair_report)
    out.models = result.document.get("stats", {}).get("models", [])
    logger.info(
        "restore started: %d records, %d files",
        len(result.records),
        len(result.files),
    )

    if load_data:
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
