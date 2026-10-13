from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass

from ..exceptions import ContainerError
from .sources import FileSource, as_source

MAGIC = b"DBSCON01"
HEADER_STRUCT = struct.Struct(">8sHHIQQQ16s8x")
HEADER_SIZE = HEADER_STRUCT.size
FORMAT_VERSION = 1

STREAM_FORMAT_VERSION = 2

FLAG_COMPRESSED = 1 << 0
FLAG_ENCRYPTED = 1 << 1
FLAG_FEC = 1 << 2

SEALED_PREFIX = struct.Struct(">8sHH")
SEALED_CHECKSUM_SIZE = 16
SEALED_MIN_SIZE = SEALED_PREFIX.size + SEALED_CHECKSUM_SIZE
SEALED_MAX_SIZE = 4096
_SEALED_PERSON = b"dbs/sealed-head"


@dataclass
class VerifiedHeader:
    version: int
    offset: int
    raw: bytes
    body: bytes = b""
    header: dict | None = None
    manifest: dict | None = None


def _manifest_hash(manifest_bytes: bytes) -> bytes:
    return hashlib.blake2b(manifest_bytes, digest_size=16).digest()


def _sealed_checksum(unsealed: bytes) -> bytes:
    return hashlib.blake2b(
        unsealed, digest_size=SEALED_CHECKSUM_SIZE, person=_SEALED_PERSON
    ).digest()


def seal_header(version: int, body: bytes) -> bytes:
    length = SEALED_PREFIX.size + len(body) + SEALED_CHECKSUM_SIZE
    if version <= FORMAT_VERSION or not SEALED_MIN_SIZE <= length <= SEALED_MAX_SIZE:
        raise ValueError("A sealed header needs version 2 or later and at most 4 KiB.")
    unsealed = SEALED_PREFIX.pack(MAGIC, version, length) + body
    return unsealed + _sealed_checksum(unsealed)


def open_sealed_header(raw: bytes) -> tuple[int, bytes] | None:
    if len(raw) < SEALED_MIN_SIZE:
        return None
    magic, version, length = SEALED_PREFIX.unpack_from(raw)
    if magic != MAGIC or version <= FORMAT_VERSION:
        return None
    if not SEALED_MIN_SIZE <= length <= min(len(raw), SEALED_MAX_SIZE):
        return None
    unsealed = bytes(raw[: length - SEALED_CHECKSUM_SIZE])
    if _sealed_checksum(unsealed) != bytes(raw[length - SEALED_CHECKSUM_SIZE : length]):
        return None
    return version, unsealed[SEALED_PREFIX.size :]


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


def _v1_layout(raw: bytes, size: int) -> dict | None:
    header = _parse_header(raw)
    if header is None or header["version"] != FORMAT_VERSION:
        return None
    m_len = header["manifest_len"]
    if header["manifest_offset"] != HEADER_SIZE:
        return None
    if header["manifest_dup_offset"] != HEADER_SIZE + m_len:
        return None
    if HEADER_SIZE + m_len > size:
        return None
    return header


def _decode_manifest(raw: bytes) -> dict | None:
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    return manifest if isinstance(manifest, dict) else None


def _verified_v1(source, offset: int) -> VerifiedHeader | None:
    raw = source.read_at(offset, HEADER_SIZE)
    header = _v1_layout(raw, source.size)
    if header is None:
        return None
    m_len = header["manifest_len"]
    for m_off in (HEADER_SIZE, HEADER_SIZE + m_len):
        candidate = source.read_at(m_off, m_len)
        if len(candidate) != m_len or _manifest_hash(candidate) != header["manifest_hash"]:
            continue
        manifest = _decode_manifest(candidate)
        if manifest is not None:
            return VerifiedHeader(
                FORMAT_VERSION, offset, raw, header=header, manifest=manifest
            )
    return None


def _verified_sealed_front(source) -> VerifiedHeader | None:
    raw = source.read_at(0, SEALED_MAX_SIZE)
    opened = open_sealed_header(raw)
    if opened is None:
        return None
    version, body = opened
    length = SEALED_PREFIX.size + len(body) + SEALED_CHECKSUM_SIZE
    return VerifiedHeader(version, 0, raw[:length], body=body)


def _verified_sealed_tail(source) -> VerifiedHeader | None:
    span = min(source.size, SEALED_MAX_SIZE)
    start = source.size - span
    tail = source.read_at(start, span)
    position = tail.rfind(MAGIC)
    while position >= 0:
        opened = open_sealed_header(tail[position:])
        if opened is not None:
            version, body = opened
            if SEALED_PREFIX.size + len(body) + SEALED_CHECKSUM_SIZE == len(tail) - position:
                return VerifiedHeader(version, start + position, tail[position:], body=body)
        position = tail.rfind(MAGIC, 0, position)
    return None


def verified_headers(source):
    source = as_source(source)
    yield from (
        found
        for found in (
            _verified_v1(source, 0),
            _verified_sealed_front(source),
        )
        if found is not None
    )
    if source.size >= 2 * HEADER_SIZE:
        back = _verified_v1(source, source.size - HEADER_SIZE)
        if back is not None:
            yield back
    tail = _verified_sealed_tail(source)
    if tail is not None and tail.offset > 0:
        yield tail


def first_verified_header(source) -> VerifiedHeader | None:
    return next(iter(verified_headers(source)), None)


def read_format_version(source) -> int | None:
    resolved = as_source(source)
    try:
        found = first_verified_header(resolved)
    finally:
        if isinstance(resolved, FileSource):
            resolved.rewind()
    return found.version if found else None


def container_version(data: bytes) -> int | None:
    return read_format_version(data)


def _unreadable_reason(source) -> str:
    for offset in (0, source.size - HEADER_SIZE):
        if offset >= 0 and _v1_layout(source.read_at(offset, HEADER_SIZE), source.size):
            return "Both manifest copies are corrupted; the backup's metadata is unrecoverable."
    return "Not a DBS container (magic header missing or corrupted)."


def unsupported_version_message(version: int) -> str:
    return (
        f"Unsupported container format version {version}; this build of DBS reads "
        f"versions {FORMAT_VERSION} and {STREAM_FORMAT_VERSION}."
    )


def _resolve_v1(data: bytes) -> VerifiedHeader:
    source = as_source(data)
    found = first_verified_header(source)
    if found is None:
        raise ContainerError(_unreadable_reason(source))
    if found.version == STREAM_FORMAT_VERSION:
        raise ContainerError(
            f"This is a format version {STREAM_FORMAT_VERSION} container; read it with "
            "dbs.container.StreamReader."
        )
    if found.version != FORMAT_VERSION:
        raise ContainerError(unsupported_version_message(found.version))
    return found


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


def _copy_len(manifest: dict) -> int:
    try:
        copy_len = int(manifest["copy_len"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ContainerError("The manifest does not record a valid payload length.") from exc
    if copy_len < 0:
        raise ContainerError("The manifest records a negative payload length.")
    return copy_len


def copy_offsets(data: bytes) -> tuple[int, int, int]:
    found = _resolve_v1(data)
    copy_len = _copy_len(found.manifest)
    copy_a_offset = HEADER_SIZE + 2 * found.header["manifest_len"]
    return copy_a_offset, copy_a_offset + copy_len, copy_len


def _complete_copy(data: bytes, offset: int, copy_len: int) -> bytes | None:
    candidate = data[offset : offset + copy_len]
    return candidate if len(candidate) == copy_len else None


def read_container(data: bytes) -> tuple[dict, bytes | None, bytes | None]:
    found = _resolve_v1(data)
    manifest = found.manifest

    copy_len = _copy_len(manifest)
    copy_a_offset = HEADER_SIZE + 2 * found.header["manifest_len"]
    copy_b_offset = copy_a_offset + copy_len

    copy_a = _complete_copy(data, copy_a_offset, copy_len)
    copy_b = _complete_copy(data, copy_b_offset, copy_len)
    if copy_a is None and copy_b is None:
        raise ContainerError(
            "Container is truncated; both payload copies are incomplete."
        )
    return manifest, copy_a, copy_b
