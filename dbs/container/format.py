from __future__ import annotations

import hashlib
import json
import struct

from ..exceptions import ContainerError

MAGIC = b"DBSCON01"
HEADER_STRUCT = struct.Struct(">8sHHIQQQ16s8x")
HEADER_SIZE = HEADER_STRUCT.size
FORMAT_VERSION = 1

FLAG_COMPRESSED = 1 << 0
FLAG_ENCRYPTED = 1 << 1
FLAG_FEC = 1 << 2


def _manifest_hash(manifest_bytes: bytes) -> bytes:
    return hashlib.blake2b(manifest_bytes, digest_size=16).digest()


def _pack_header(
    *, flags: int, block_size: int, manifest_offset: int, manifest_len: int,
    manifest_dup_offset: int, manifest_hash: bytes,
) -> bytes:
    return HEADER_STRUCT.pack(
        MAGIC,
        FORMAT_VERSION,
        flags,
        block_size,
        manifest_offset,
        manifest_len,
        manifest_dup_offset,
        manifest_hash,
    )


def _parse_header(raw: bytes) -> dict | None:
    if len(raw) < HEADER_SIZE:
        return None
    try:
        magic, version, flags, block_size, m_off, m_len, m_dup, m_hash = (
            HEADER_STRUCT.unpack(raw[:HEADER_SIZE])
        )
    except struct.error:
        return None
    if magic != MAGIC:
        return None
    return {
        "version": version,
        "flags": flags,
        "block_size": block_size,
        "manifest_offset": m_off,
        "manifest_len": m_len,
        "manifest_dup_offset": m_dup,
        "manifest_hash": m_hash,
    }


def write_container(manifest: dict, copy_a: bytes, copy_b: bytes, *, flags: int) -> bytes:
    manifest_bytes = json.dumps(manifest, separators=(",", ":")).encode("utf-8")
    manifest_len = len(manifest_bytes)
    manifest_offset = HEADER_SIZE
    manifest_dup_offset = manifest_offset + manifest_len

    header = _pack_header(
        flags=flags,
        block_size=int(manifest["blocks"]["block_size"]),
        manifest_offset=manifest_offset,
        manifest_len=manifest_len,
        manifest_dup_offset=manifest_dup_offset,
        manifest_hash=_manifest_hash(manifest_bytes),
    )

    return b"".join(
        [
            header,
            manifest_bytes,
            manifest_bytes,
            copy_a,
            copy_b,
            header,
        ]
    )


def _read_manifest(data: bytes, header: dict) -> dict:
    expected = header["manifest_hash"]
    m_len = header["manifest_len"]
    for offset in (header["manifest_offset"], header["manifest_dup_offset"]):
        candidate = data[offset : offset + m_len]
        if len(candidate) == m_len and _manifest_hash(candidate) == expected:
            return json.loads(candidate.decode("utf-8"))
    raise ContainerError(
        "Both manifest copies are corrupted; the backup's metadata is unrecoverable."
    )


def copy_offsets(data: bytes) -> tuple[int, int, int]:
    header = _parse_header(data[:HEADER_SIZE]) or _parse_header(data[-HEADER_SIZE:])
    if header is None:
        raise ContainerError("Not a DBS container (magic header missing or corrupted).")
    manifest = _read_manifest(data, header)
    copy_len = int(manifest["copy_len"])
    copy_a_offset = header["manifest_offset"] + 2 * header["manifest_len"]
    return copy_a_offset, copy_a_offset + copy_len, copy_len


def read_container(data: bytes) -> tuple[dict, bytes, bytes]:
    header = _parse_header(data[:HEADER_SIZE])
    if header is None and len(data) >= HEADER_SIZE:
        header = _parse_header(data[-HEADER_SIZE:])
    if header is None:
        raise ContainerError("Not a DBS container (magic header missing or corrupted).")

    manifest = _read_manifest(data, header)

    copy_len = int(manifest["copy_len"])
    copy_a_offset = header["manifest_offset"] + 2 * header["manifest_len"]
    copy_b_offset = copy_a_offset + copy_len

    copy_a = data[copy_a_offset : copy_a_offset + copy_len]
    copy_b = data[copy_b_offset : copy_b_offset + copy_len]
    if len(copy_a) != copy_len or len(copy_b) != copy_len:
        raise ContainerError("Container is truncated; payload copies are incomplete.")
    return manifest, copy_a, copy_b
