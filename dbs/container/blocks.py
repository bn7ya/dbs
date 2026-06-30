from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from reedsolo import RSCodec, ReedSolomonError

DEFAULT_BLOCK_SIZE = 65536

DEFAULT_NSYM = 16


def _hash(data: bytes) -> str:
    return hashlib.blake2b(data, digest_size=16).hexdigest()


@dataclass
class BlockPlan:
    block_size: int
    nsym: int
    ciphertext_len: int
    enc_lens: list[int] = field(default_factory=list)
    enc_hashes: list[str] = field(default_factory=list)
    data_hashes: list[str] = field(default_factory=list)

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
    total_blocks: int = 0
    blocks_direct: int = 0
    blocks_rs_corrected: int = 0
    blocks_used_b: int = 0
    failed_blocks: list[int] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed_blocks

    @property
    def healed(self) -> bool:
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
    try:
        decoded = rsc.decode(encoded)
    except ReedSolomonError:
        return None
    except Exception:
        return None
    data = bytes(decoded[0]) if isinstance(decoded, tuple) else bytes(decoded)
    return data if _hash(data) == data_hash else None


def repair_copies(
    copy_a: bytes,
    copy_b: bytes,
    plan: BlockPlan,
) -> tuple[bytes | None, RepairReport]:
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
    if len(ciphertext) != plan.ciphertext_len:
        ciphertext = ciphertext[: plan.ciphertext_len]
    return ciphertext, report
