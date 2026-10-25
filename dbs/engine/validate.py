from __future__ import annotations

from dataclasses import dataclass, field

from ..container import StreamReader, read_format_version, repair_copies
from ..container.blocks import BlockPlan, RepairReport
from ..container.format import STREAM_FORMAT_VERSION, read_container
from ..exceptions import DBSError
from .frames import malformed
from .inputs import opened, stream_source, whole


@dataclass
class ValidationResult:
    ok: bool
    repair_report: RepairReport | None = None
    decrypted_ok: bool | None = None
    stats: dict = field(default_factory=dict)
    messages: list = field(default_factory=list)

    def summary(self) -> str:
        lines = []
        if self.repair_report is not None:
            lines.append(self.repair_report.summary())
        if self.decrypted_ok is True:
            lines.append("Decryption + payload hash: OK")
        elif self.decrypted_ok is False:
            lines.append("Decryption + payload hash: FAILED")
        lines.extend(self.messages)
        verdict = "VALID" if self.ok else "INVALID"
        return f"[{verdict}] " + " | ".join(lines)


def validate_backup(data, passphrase: str | None = None) -> ValidationResult:
    """Validate the backup in ``data``: its bytes, a path, or a binary file object.

    Every block of both copies is checked; with ``passphrase`` the payload is
    also decrypted and read end to end. A format 2 backup is read as a stream.
    Damage, a wrong passphrase or a file that is not a backup come back as
    ``ok=False`` with the reason in ``messages``; only a file that cannot be
    opened raises, with its ``OSError``.
    """
    with opened(data) as handle:
        try:
            version = read_format_version(handle)
        except DBSError as exc:
            return ValidationResult(ok=False, messages=[str(exc)])
        if version == STREAM_FORMAT_VERSION:
            return _validate_stream(handle, passphrase)
        return _validate_v1(whole(handle), passphrase)


def _validate_v1(data: bytes, passphrase: str | None) -> ValidationResult:
    try:
        manifest, copy_a, copy_b = read_container(data)
    except DBSError as exc:
        return ValidationResult(ok=False, messages=[str(exc)])

    plan = BlockPlan.from_dict(manifest["blocks"])
    ciphertext, report = repair_copies(copy_a, copy_b, plan)
    result = ValidationResult(
        ok=report.ok,
        repair_report=report,
        stats=manifest.get("stats", {}),
    )

    if passphrase is not None and ciphertext is not None:
        try:
            from .restore import _read_v1_payload

            read_result = _read_v1_payload(data, passphrase)
            result.decrypted_ok = True
            result.stats = read_result.document.get("stats", {})
        except DBSError as exc:
            result.decrypted_ok = False
            result.ok = False
            result.messages.append(str(exc))

    return result


def _validate_stream(handle, passphrase: str | None) -> ValidationResult:
    from .restore import open_reader, read_frames

    if passphrase is None:
        try:
            report = StreamReader(stream_source(handle)).verify()
        except DBSError as exc:
            return ValidationResult(ok=False, messages=[str(exc)])
        return ValidationResult(ok=report.ok, repair_report=report)
    try:
        reader, source = open_reader(handle, passphrase)
    except DBSError as exc:
        return ValidationResult(ok=False, decrypted_ok=False, messages=[str(exc)])
    result = ValidationResult(ok=False, decrypted_ok=False)
    try:
        with read_frames(reader, source, check_spares=True) as payload:
            result.stats = _read_through(payload)
    except DBSError as exc:
        result.messages.append(str(exc))
    else:
        result.decrypted_ok = True
        result.ok = reader.report.ok
    result.repair_report = reader.report
    return result


def _read_through(payload) -> dict:
    payload.read_header()
    payload.read_manifest()
    files = 0
    for stream in payload.files():
        stream.drain()
        files += 0 if stream.skipped else 1
    counts: dict = {}
    for batch in payload.record_batches():
        for record in batch:
            counts[record["model"]] = counts.get(record["model"], 0) + 1
    payload.read_trailer()
    payload.finish()
    stats = payload.stats
    recorded = {item["model"]: item["count"] for item in stats["models"] if item["count"]}
    if recorded != counts or stats["records"] != sum(counts.values()):
        raise malformed("its trailer's record counts disagree with its records")
    if stats["files"] != files:
        raise malformed("its trailer's file counts disagree with its files")
    return stats
