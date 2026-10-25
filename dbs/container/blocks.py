from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from reedsolo import RSCodec

from . import rs

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
    blocks_merged: int = 0
    copies_available: int = 2
    failed_blocks: list[int] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed_blocks

    @property
    def healed(self) -> bool:
        return self.ok and bool(
            self.blocks_rs_corrected
            or self.blocks_used_b
            or self.blocks_merged
            or self.copies_available < 2
        )

    def summary(self) -> str:
        if not self.ok:
            return (
                f"UNRECOVERABLE: {len(self.failed_blocks)}/{self.total_blocks} "
                f"blocks could not be repaired (indices: {self.failed_blocks[:10]}"
                f"{'...' if len(self.failed_blocks) > 10 else ''})"
            )
        if self.healed:
            details = [
                f"{self.blocks_rs_corrected} Reed-Solomon corrected",
                f"{self.blocks_used_b} restored from the second copy",
            ]
            if self.blocks_merged:
                details.append(f"{self.blocks_merged} rebuilt from both copies")
            if self.copies_available < 2:
                details.append(
                    "one payload copy lost to truncation; "
                    "recovered from the surviving copy"
                )
            return (
                f"REPAIRED: {self.total_blocks} blocks intact after healing "
                f"({', '.join(details)})"
            )
        return f"CLEAN: all {self.total_blocks} blocks verified, no repair needed"


def _decode_with_reedsolo(rsc: RSCodec, encoded: bytes, data_hash: str) -> bytes | None:
    try:
        decoded = rsc.decode(encoded)
    except rs.UNDECODABLE:
        return None
    data = bytes(decoded[0]) if isinstance(decoded, tuple) else bytes(decoded)
    return data if _hash(data) == data_hash else None


def _decode_codeword(rsc: RSCodec, codeword: bytes, erasures=None) -> bytes | None:
    try:
        decoded = rsc.decode(codeword, erase_pos=erasures) if erasures else rsc.decode(codeword)
    except rs.UNDECODABLE:
        return None
    return bytes(decoded[0]) if isinstance(decoded, tuple) else bytes(decoded)


def _rebuild_codeword(rsc: RSCodec, first: bytes, second: bytes) -> bytes | None:
    for codeword in (first, second):
        data = _decode_codeword(rsc, codeword)
        if data is not None:
            return data
    differing = [index for index, (a, b) in enumerate(zip(first, second)) if a != b]
    if not differing or len(differing) > rsc.nsym:
        return None
    for codeword in (first, second):
        data = _decode_codeword(rsc, codeword, differing)
        if data is not None:
            return data
    return None


def _rebuild_from_both(rsc: RSCodec, encoded: list[bytes], data_hash: str) -> bytes | None:
    if len(encoded) != 2 or len(encoded[0]) != len(encoded[1]):
        return None
    first, second = encoded
    pieces: list[bytes] = []
    for start in range(0, len(first), rsc.nsize):
        piece = _rebuild_codeword(
            rsc, first[start : start + rsc.nsize], second[start : start + rsc.nsize]
        )
        if piece is None:
            return None
        pieces.append(piece)
    data = b"".join(pieces)
    return data if _hash(data) == data_hash else None


def _decode_block(rsc: RSCodec, encoded: bytes, data_hash: str) -> bytes | None:
    if rsc.nsize != rs.CODEWORD_SIZE or not rs.MIN_NSYM <= rsc.nsym <= rs.MAX_NSYM:
        return _decode_with_reedsolo(rsc, encoded, data_hash)
    stripped = rs.strip_parity(encoded, rsc.nsym)
    if stripped is not None and _hash(stripped) == data_hash:
        return stripped
    data = rs.decode(encoded, rsc.nsym)
    return data if data is not None and _hash(data) == data_hash else None


def repair_copies(
    copy_a: bytes | None,
    copy_b: bytes | None,
    plan: BlockPlan,
) -> tuple[bytes | None, RepairReport]:
    sources = [
        (label, source)
        for label, source in (("a", copy_a), ("b", copy_b))
        if source is not None
    ]
    rsc = RSCodec(plan.nsym)
    report = RepairReport(total_blocks=plan.n_blocks, copies_available=len(sources))
    chunks: list[bytes] = []
    offset = 0
    for index, (enc_len, enc_hash, data_hash) in enumerate(
        zip(plan.enc_lens, plan.enc_hashes, plan.data_hashes)
    ):
        chosen: bytes | None = None
        used_b = False
        needed_rs = False
        encoded_copies = [source[offset : offset + enc_len] for _, source in sources]
        for (label, _), encoded in zip(sources, encoded_copies):
            stored_intact = _hash(encoded) == enc_hash
            data = _decode_block(rsc, encoded, data_hash)
            if data is not None:
                chosen = data
                used_b = label == "b"
                needed_rs = not stored_intact
                break
        offset += enc_len

        merged = False
        if chosen is None:
            chosen = _rebuild_from_both(rsc, encoded_copies, data_hash)
            merged = chosen is not None

        if chosen is None:
            report.failed_blocks.append(index)
            chunks.append(b"")
            continue

        if merged:
            report.blocks_merged += 1
            chunks.append(chosen)
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
