"""Block framing, per-block hashing, Reed-Solomon FEC and the dual-copy repair.

Why both two copies *and* Reed-Solomon? They cover different failure modes:

* A block destroyed wholesale in one copy is restored from the other copy.
* A handful of flipped bits (the realistic non-ECC-RAM "bit rot" case) in a
  block is corrected in-place by Reed-Solomon, even if *both* copies are hit,
  as long as the damage stays within the parity budget.

Every recovered block is verified against a stored BLAKE2b hash of the clean
ciphertext, so a Reed-Solomon mis-correction can never slip through unnoticed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from reedsolo import RSCodec, ReedSolomonError

# Plaintext (ciphertext) bytes per full block before Reed-Solomon expansion.
DEFAULT_BLOCK_SIZE = 65536

# Reed-Solomon parity bytes per 255-byte codeword. 16 parity bytes corrects up
# to 8 corrupted bytes per 255-byte codeword (~6.7% size overhead).
DEFAULT_NSYM = 16


def _hash(data: bytes) -> str:
    return hashlib.blake2b(data, digest_size=16).hexdigest()


@dataclass
class BlockPlan:
    """Metadata describing how one encrypted copy is framed into blocks.

    The two stored copies are byte-identical, so a single plan describes both.
    """

    block_size: int
    nsym: int
    ciphertext_len: int
    enc_lens: list[int] = field(default_factory=list)
    enc_hashes: list[str] = field(default_factory=list)  # hash of stored encoded block
    data_hashes: list[str] = field(default_factory=list)  # hash of clean ciphertext block

    @property
    def copy_len(self) -> int:
        return sum(self.enc_lens)

    @property
    def n_blocks(self) -> int:
        return len(self.enc_lens)

    def to_dict(self) -> dict:
        return {
            "block_size": self.block_size,
            "nsym": self.nsym,
            "ciphertext_len": self.ciphertext_len,
            "enc_lens": self.enc_lens,
            "enc_hashes": self.enc_hashes,
            "data_hashes": self.data_hashes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BlockPlan":
        return cls(
            block_size=int(data["block_size"]),
            nsym=int(data["nsym"]),
            ciphertext_len=int(data["ciphertext_len"]),
            enc_lens=list(data["enc_lens"]),
            enc_hashes=list(data["enc_hashes"]),
            data_hashes=list(data["data_hashes"]),
        )


@dataclass
class RepairReport:
    """Outcome of reassembling the encrypted stream from the two copies."""

    total_blocks: int = 0
    blocks_direct: int = 0       # at least one copy stored the block intact
    blocks_rs_corrected: int = 0  # stored bytes were corrupt, RS recovered them
    blocks_used_b: int = 0       # primary copy A was bad, fell back to copy B
    failed_blocks: list[int] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed_blocks

    @property
    def healed(self) -> bool:
        """True when corruption was present but fully repaired."""
        return self.ok and (self.blocks_rs_corrected or self.blocks_used_b)

    def summary(self) -> str:
        if not self.ok:
            return (
                f"UNRECOVERABLE: {len(self.failed_blocks)}/{self.total_blocks} "
                f"blocks could not be repaired (indices: {self.failed_blocks[:10]}"
                f"{'...' if len(self.failed_blocks) > 10 else ''})"
            )
        if self.healed:
            return (
                f"REPAIRED: {self.total_blocks} blocks intact after healing "
                f"({self.blocks_rs_corrected} Reed-Solomon corrected, "
                f"{self.blocks_used_b} restored from the second copy)"
            )
        return f"CLEAN: all {self.total_blocks} blocks verified, no repair needed"


def encode_copy(
    ciphertext: bytes,
    block_size: int = DEFAULT_BLOCK_SIZE,
    nsym: int = DEFAULT_NSYM,
) -> tuple[bytes, BlockPlan]:
    """Frame ``ciphertext`` into Reed-Solomon protected blocks.

    Returns the bytes for *one* stored copy plus a :class:`BlockPlan`. The
    caller writes the returned bytes twice (copy A and copy B).
    """
    rsc = RSCodec(nsym)
    plan = BlockPlan(block_size=block_size, nsym=nsym, ciphertext_len=len(ciphertext))
    parts: list[bytes] = []
    for offset in range(0, len(ciphertext), block_size):
        block = ciphertext[offset : offset + block_size]
        encoded = bytes(rsc.encode(block))
        parts.append(encoded)
        plan.enc_lens.append(len(encoded))
        plan.enc_hashes.append(_hash(encoded))
        plan.data_hashes.append(_hash(block))
    return b"".join(parts), plan


def _decode_block(rsc: RSCodec, encoded: bytes, data_hash: str) -> bytes | None:
    """Reed-Solomon decode ``encoded`` and verify it against ``data_hash``."""
    try:
        decoded = rsc.decode(encoded)
    except ReedSolomonError:
        return None
    except Exception:  # defensive: malformed/short input can raise other errors -> miss
        return None
    # reedsolo returns a (msg, msg_ecc, errata) tuple on newer versions and a
    # bare bytearray on very old ones; normalise to the message bytes.
    data = bytes(decoded[0]) if isinstance(decoded, tuple) else bytes(decoded)
    return data if _hash(data) == data_hash else None


def repair_copies(
    copy_a: bytes,
    copy_b: bytes,
    plan: BlockPlan,
) -> tuple[bytes | None, RepairReport]:
    """Reassemble the clean ciphertext from the two (possibly damaged) copies.

    Returns ``(ciphertext, report)``. ``ciphertext`` is ``None`` when at least
    one block could not be recovered from either copy or by Reed-Solomon; the
    report names the offending block indices.
    """
    rsc = RSCodec(plan.nsym)
    report = RepairReport(total_blocks=plan.n_blocks)
    chunks: list[bytes] = []
    offset = 0
    for index, (enc_len, enc_hash, data_hash) in enumerate(
        zip(plan.enc_lens, plan.enc_hashes, plan.data_hashes)
    ):
        a = copy_a[offset : offset + enc_len]
        b = copy_b[offset : offset + enc_len]
        offset += enc_len

        chosen: bytes | None = None
        used_b = False
        needed_rs = False
        for label, encoded in (("a", a), ("b", b)):
            stored_intact = _hash(encoded) == enc_hash
            data = _decode_block(rsc, encoded, data_hash)
            if data is not None:
                chosen = data
                used_b = label == "b"
                needed_rs = not stored_intact
                break

        if chosen is None:
            report.failed_blocks.append(index)
            chunks.append(b"")
            continue

        if used_b:
            report.blocks_used_b += 1
        if needed_rs:
            report.blocks_rs_corrected += 1
        else:
            report.blocks_direct += 1
        chunks.append(chosen)

    if report.failed_blocks:
        return None, report

    ciphertext = b"".join(chunks)
    if len(ciphertext) != plan.ciphertext_len:  # defensive truncation
        ciphertext = ciphertext[: plan.ciphertext_len]
    return ciphertext, report
