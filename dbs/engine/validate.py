"""Integrity check that never touches the database or filesystem.

Without a passphrase it reports the *structural* health of the container: which
blocks are intact, which were healed, and whether anything is unrecoverable.
With a passphrase it additionally confirms the payload decrypts and matches its
stored hash end-to-end.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..container import repair_copies
from ..container.blocks import BlockPlan, RepairReport
from ..container.format import read_container
from ..exceptions import DBSError


@dataclass
class ValidationResult:
    ok: bool
    repair_report: RepairReport | None = None
    decrypted_ok: bool | None = None  # None when no passphrase was supplied
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


def validate_backup(data: bytes, passphrase: str | None = None) -> ValidationResult:
    """Validate container ``data``; decrypt-check too when ``passphrase`` given."""
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
            from .restore import read_payload

            read_payload(data, passphrase)
            result.decrypted_ok = True
        except DBSError as exc:
            result.decrypted_ok = False
            result.ok = False
            result.messages.append(str(exc))

    return result
