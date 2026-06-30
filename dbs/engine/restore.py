from __future__ import annotations

import hashlib
import zlib
from dataclasses import dataclass, field

from ..container import repair_copies
from ..container.blocks import BlockPlan, RepairReport
from ..container.format import read_container
from ..crypto import decrypt_payload
from ..crypto.envelope import EnvelopeMaterial
from ..exceptions import CorruptionError
from ..files import FileEntry, restore_file
from ..serialize import load_records
from .payload import unpack_payload


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
    plan = BlockPlan.from_dict(manifest["blocks"])

    ciphertext, report = repair_copies(copy_a, copy_b, plan)
    if ciphertext is None:
        raise CorruptionError(
            "Backup is damaged beyond repair: " + report.summary(), report
        )

    material = EnvelopeMaterial.from_dict(manifest["crypto"])
    body = decrypt_payload(ciphertext, passphrase, material)
    payload = zlib.decompress(body) if manifest.get("compression") == "zlib" else body

    if hashlib.sha256(payload).hexdigest() != manifest["payload_sha256"]:
        raise CorruptionError(
            "Decrypted payload failed its integrity hash; refusing to restore.", report
        )

    document, records, files = unpack_payload(payload)
    return ReadResult(manifest, document, records, files, report)


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

    if load_data:
        out.records_loaded = load_records(result.records, using=using)
    if write_files:
        for entry, file_bytes in result.files:
            restore_file(entry, file_bytes)
            out.files_written += 1
    return out
