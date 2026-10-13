from __future__ import annotations

import dataclasses
import hashlib
import os
import struct
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..crypto.chunked import (
    MAX_CHUNKS,
    NONCE_LENGTH,
    TAG_LENGTH,
    WRAPPED_KEY_LENGTH,
    ChunkCipher,
    new_nonce_prefix,
    unwrap_key,
    wrap_key,
)
from ..crypto.kdf import SALT_LENGTH, KDFParams, derive_key
from ..exceptions import ContainerError, CorruptionError, CryptoError
from . import rs
from .blocks import DEFAULT_BLOCK_SIZE, DEFAULT_NSYM, RepairReport
from .format import (
    FORMAT_VERSION as V1_FORMAT_VERSION,
    SEALED_CHECKSUM_SIZE,
    SEALED_PREFIX,
    STREAM_FORMAT_VERSION,
    first_verified_header,
    open_sealed_header,
    seal_header,
    unsupported_version_message,
)
from .sources import as_source

FORMAT_VERSION = STREAM_FORMAT_VERSION

DEFAULT_INTERLEAVE = 64

DEFAULT_WORKERS = 1

MIN_BLOCK_SIZE = 512

MAX_BLOCK_SIZE = 16 * 1024 * 1024

MIN_NSYM = 2

MAX_NSYM = 128

MAX_INTERLEAVE = 4096

MAX_WINDOW_BYTES = 64 * 1024 * 1024

MAX_BLOCKS = MAX_CHUNKS - 1

BATCH_BLOCKS = 16

READ_BATCH_SLOTS = 16

SCAN_BATCH_BLOCKS = 256

CONTAINER_ID_LENGTH = 16

SLOT_TAG_SIZE = 16

DESCRIPTOR = struct.Struct(">QIB3x")

FINAL_FLAG = 1

CHUNK_OVERHEAD = DESCRIPTOR.size + TAG_LENGTH

HEADER_BODY = struct.Struct(">HHIIIIHH16s16s7sx12s48s")

HEADER_PAD_OFFSET = struct.calcsize(">HHIIIIHH16s16s7s")

HEADER_SIZE = SEALED_PREFIX.size + HEADER_BODY.size + SEALED_CHECKSUM_SIZE

KEY_BINDING_SIZE = HEADER_BODY.size - NONCE_LENGTH - WRAPPED_KEY_LENGTH

TRAILER_MARKER = b"DBSEND02"

TRAILER_BODY = struct.Struct(">8sHH16sQQI4x32s")

TRAILER_PAD = slice(struct.calcsize(">8sHH16sQQI"), struct.calcsize(">8sHH16sQQI4x"))

TRAILER_SIZE = TRAILER_BODY.size + SEALED_CHECKSUM_SIZE

_SLOT_PERSON = b"dbs/v2-slot"

_DIGEST_PERSON = b"dbs/v2-blocks"

_TRAILER_PERSON = b"dbs/v2-trailer"

_ZERO_RESERVED = bytes(DESCRIPTOR.size - 13)


def _as_bytes(value) -> bytes:
    return value.encode("utf-8") if isinstance(value, str) else bytes(value)


def layout_problem(block_size, nsym, interleave) -> str | None:
    for name, value in (("block_size", block_size), ("nsym", nsym), ("interleave", interleave)):
        if not isinstance(value, int) or isinstance(value, bool):
            return f"{name} must be an integer, got {value!r}."
    if not MIN_BLOCK_SIZE <= block_size <= MAX_BLOCK_SIZE:
        return f"block_size={block_size} is outside [{MIN_BLOCK_SIZE}, {MAX_BLOCK_SIZE}]."
    if not MIN_NSYM <= nsym <= MAX_NSYM:
        return f"nsym={nsym} is outside [{MIN_NSYM}, {MAX_NSYM}]."
    if not 1 <= interleave <= MAX_INTERLEAVE:
        return f"interleave={interleave} is outside [1, {MAX_INTERLEAVE}]."
    window = interleave * (rs.encoded_length(block_size, nsym) + SLOT_TAG_SIZE)
    if window > MAX_WINDOW_BYTES:
        return (
            f"interleave={interleave} with block_size={block_size} needs a {window} byte "
            f"window, above the {MAX_WINDOW_BYTES} byte limit."
        )
    return None


@dataclass(frozen=True)
class StreamLayout:
    block_size: int = DEFAULT_BLOCK_SIZE
    nsym: int = DEFAULT_NSYM
    interleave: int = DEFAULT_INTERLEAVE

    @property
    def encoded_size(self) -> int:
        return rs.encoded_length(self.block_size, self.nsym)

    @property
    def slot_size(self) -> int:
        return self.encoded_size + SLOT_TAG_SIZE

    @property
    def chunk_capacity(self) -> int:
        return self.block_size - CHUNK_OVERHEAD

    @property
    def max_chunk_len(self) -> int:
        return self.block_size - DESCRIPTOR.size

    def container_size(self, blocks: int) -> int:
        return 2 * HEADER_SIZE + 2 * TRAILER_SIZE + 2 * blocks * self.slot_size

    def burst_tolerance(self, blocks: int) -> int:
        distance = self.interleave if blocks > self.interleave else blocks - 1
        return max(distance, 0) * self.slot_size


@dataclass(frozen=True)
class StreamHeader:
    flags: int
    layout: StreamLayout
    kdf_params: KDFParams
    salt: bytes
    container_id: bytes
    nonce_prefix: bytes
    wrap_nonce: bytes = bytes(NONCE_LENGTH)
    wrapped_key: bytes = bytes(WRAPPED_KEY_LENGTH)

    def pack_body(self) -> bytes:
        return HEADER_BODY.pack(
            self.flags,
            self.layout.nsym,
            self.layout.block_size,
            self.layout.interleave,
            self.kdf_params.time_cost,
            self.kdf_params.memory_cost,
            self.kdf_params.parallelism,
            0,
            self.salt,
            self.container_id,
            self.nonce_prefix,
            self.wrap_nonce,
            self.wrapped_key,
        )

    def key_binding(self) -> bytes:
        return self.pack_body()[:KEY_BINDING_SIZE]

    def seal(self) -> bytes:
        return seal_header(FORMAT_VERSION, self.pack_body())

    @classmethod
    def parse(cls, body: bytes) -> "StreamHeader":
        if len(body) != HEADER_BODY.size:
            raise ContainerError("The format version 2 header has the wrong size.")
        (
            flags, nsym, block_size, interleave, time_cost, memory_cost, parallelism,
            reserved, salt, container_id, nonce_prefix, wrap_nonce, wrapped_key,
        ) = HEADER_BODY.unpack(body)
        if reserved or body[HEADER_PAD_OFFSET] != 0:
            raise ContainerError("The format version 2 header has unknown fields set.")
        problem = layout_problem(block_size, nsym, interleave)
        if problem:
            raise ContainerError(f"The header describes an unusable layout: {problem}")
        params = KDFParams(time_cost=time_cost, memory_cost=memory_cost, parallelism=parallelism)
        try:
            params.validate_untrusted()
        except CryptoError as exc:
            raise ContainerError(f"The header's key-derivation parameters are refused: {exc}") from exc
        return cls(
            flags=flags,
            layout=StreamLayout(block_size, nsym, interleave),
            kdf_params=params,
            salt=salt,
            container_id=container_id,
            nonce_prefix=nonce_prefix,
            wrap_nonce=wrap_nonce,
            wrapped_key=wrapped_key,
        )


def _trailer_checksum(body: bytes) -> bytes:
    return hashlib.blake2b(body, digest_size=SEALED_CHECKSUM_SIZE, person=_TRAILER_PERSON).digest()


@dataclass(frozen=True)
class StreamTrailer:
    container_id: bytes
    blocks: int
    plaintext_bytes: int
    final_chunk_len: int
    blocks_digest: bytes

    def seal(self) -> bytes:
        body = TRAILER_BODY.pack(
            TRAILER_MARKER,
            FORMAT_VERSION,
            TRAILER_SIZE,
            self.container_id,
            self.blocks,
            self.plaintext_bytes,
            self.final_chunk_len,
            self.blocks_digest,
        )
        return body + _trailer_checksum(body)

    @classmethod
    def open(cls, raw: bytes, header: StreamHeader) -> "StreamTrailer | None":
        if len(raw) != TRAILER_SIZE:
            return None
        body = raw[: TRAILER_BODY.size]
        if _trailer_checksum(body) != raw[TRAILER_BODY.size :]:
            return None
        marker, version, length, container_id, blocks, plaintext_bytes, final_len, digest = (
            TRAILER_BODY.unpack(body)
        )
        layout = header.layout
        if marker != TRAILER_MARKER or version != FORMAT_VERSION or length != TRAILER_SIZE:
            return None
        if container_id != header.container_id or body[TRAILER_PAD] != bytes(4):
            return None
        if not 1 <= blocks <= MAX_BLOCKS:
            return None
        if not TAG_LENGTH <= final_len <= layout.max_chunk_len:
            return None
        if plaintext_bytes != (blocks - 1) * layout.chunk_capacity + final_len - TAG_LENGTH:
            return None
        return cls(container_id, blocks, plaintext_bytes, final_len, digest)


def _slot_tag(container_id: bytes, encoded) -> bytes:
    return hashlib.blake2b(
        encoded, digest_size=SLOT_TAG_SIZE, key=container_id, person=_SLOT_PERSON
    ).digest()


def _blocks_digest(container_id: bytes):
    return hashlib.blake2b(digest_size=32, key=container_id, person=_DIGEST_PERSON)


def first_copy_position(index: int, interleave: int) -> int:
    return index if index < interleave else 2 * index - interleave


def schedule(blocks: int, interleave: int):
    position = 0
    for step in range(blocks + interleave):
        if step < blocks:
            yield position, step, True
            position += 1
        if step >= interleave:
            yield position, step - interleave, False
            position += 1


@dataclass
class StreamSummary:
    container_bytes: int
    plaintext_bytes: int
    blocks: int
    block_size: int
    nsym: int
    interleave: int
    slot_size: int
    sha256: str
    correctable_bytes_per_codeword: int
    burst_tolerance_bytes: int


@dataclass
class StreamRepairReport(RepairReport):
    blocks_merged: int = 0
    spares_damaged: list[int] = field(default_factory=list)
    metadata_damaged: list[str] = field(default_factory=list)
    unverified_blocks: list[int] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed_blocks and not self.problems

    @property
    def healed(self) -> bool:
        return self.ok and bool(
            self.blocks_rs_corrected
            or self.blocks_used_b
            or self.blocks_merged
            or self.copies_available < 2
            or self.spares_damaged
            or self.metadata_damaged
        )

    def summary(self) -> str:
        if not self.ok:
            parts = []
            if self.failed_blocks:
                parts.append(
                    f"{len(self.failed_blocks)}/{self.total_blocks} blocks could not be "
                    f"repaired (indices: {self.failed_blocks[:10]}"
                    f"{'...' if len(self.failed_blocks) > 10 else ''})"
                )
            parts.extend(self.problems)
            return "UNRECOVERABLE: " + "; ".join(parts)
        notes = []
        if self.unverified_blocks:
            notes.append(
                f"{len(self.unverified_blocks)} rebuilt blocks could not be checked "
                "against a stored hash"
            )
        if self.healed:
            details = [
                f"{self.blocks_rs_corrected} Reed-Solomon corrected",
                f"{self.blocks_used_b} restored from the second copy",
            ]
            if self.blocks_merged:
                details.append(f"{self.blocks_merged} rebuilt from both copies")
            if self.spares_damaged:
                details.append(f"{len(self.spares_damaged)} unused second copies damaged")
            if self.metadata_damaged:
                details.append("damaged metadata copies: " + ", ".join(self.metadata_damaged))
            if self.copies_available < 2:
                details.append("part of the second copy lost to truncation")
            text = (
                f"REPAIRED: {self.total_blocks} blocks intact after healing "
                f"({', '.join(details)})"
            )
        else:
            text = f"CLEAN: all {self.total_blocks} blocks verified, no repair needed"
        return text + "".join(f"; {note}" for note in notes)


class StreamWriter:
    def __init__(
        self,
        sink,
        passphrase,
        *,
        kdf_params: KDFParams | None = None,
        block_size: int = DEFAULT_BLOCK_SIZE,
        nsym: int = DEFAULT_NSYM,
        interleave: int = DEFAULT_INTERLEAVE,
        workers: int | None = None,
        flags: int = 0,
    ):
        problem = layout_problem(block_size, nsym, interleave)
        if problem:
            raise ValueError(problem)
        if not isinstance(flags, int) or not 0 <= flags <= 0xFFFF:
            raise ValueError(f"flags must fit in 16 bits, got {flags!r}.")
        workers = DEFAULT_WORKERS if workers is None else workers
        if not isinstance(workers, int) or workers < 1:
            raise ValueError(f"workers must be a positive integer, got {workers!r}.")
        params = kdf_params or KDFParams()
        params.validate_untrusted()

        self.layout = StreamLayout(block_size, nsym, interleave)
        salt = os.urandom(SALT_LENGTH)
        unwrapped = StreamHeader(
            flags=flags,
            layout=self.layout,
            kdf_params=params,
            salt=salt,
            container_id=os.urandom(CONTAINER_ID_LENGTH),
            nonce_prefix=new_nonce_prefix(),
        )
        kek = derive_key(_as_bytes(passphrase), salt, params)
        self._data_key = AESGCM.generate_key(bit_length=256)
        wrap_nonce, wrapped_key = wrap_key(kek, self._data_key, unwrapped.key_binding())
        self.header = dataclasses.replace(
            unwrapped, wrap_nonce=wrap_nonce, wrapped_key=wrapped_key
        )
        self._sealed_header = self.header.seal()

        self._sink = sink
        self._workers = workers
        self._pool = None
        self._sha256 = hashlib.sha256()
        self._digest = _blocks_digest(self.header.container_id)
        self._window: deque = deque()
        self._batch: list[bytes] = []
        self._pending = bytearray()
        self._next_index = 0
        self._plaintext_bytes = 0
        self._container_bytes = 0
        self._final_chunk_len = 0
        self._summary: StreamSummary | None = None
        self._closed = False
        self._emit(self._sealed_header)
        if workers > 1:
            self._pool = ThreadPoolExecutor(workers)

    def __enter__(self) -> "StreamWriter":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if exc_type is None:
            self.close()
        else:
            self.abort()

    def write(self, data) -> int:
        self._ensure_open()
        view = memoryview(data).cast("B")
        size = len(view)
        capacity = self.layout.chunk_capacity
        offset = 0
        if self._pending and size:
            room = capacity - len(self._pending)
            self._pending += view[:room]
            offset = min(room, size)
            if offset < size:
                self._queue(bytes(self._pending))
                self._pending = bytearray()
        while size - offset > capacity:
            self._queue(bytes(view[offset : offset + capacity]))
            offset += capacity
        self._pending += view[offset:]
        self._plaintext_bytes += size
        return size

    def close(self) -> StreamSummary:
        if self._summary is not None:
            return self._summary
        self._ensure_open()
        try:
            final_chunk = bytes(self._pending)
            self._pending = bytearray()
            self._final_chunk_len = len(final_chunk) + TAG_LENGTH
            self._batch.append(final_chunk)
            self._flush(final=True)
            while self._window:
                self._emit(self._window.popleft())
            trailer = StreamTrailer(
                container_id=self.header.container_id,
                blocks=self._next_index,
                plaintext_bytes=self._plaintext_bytes,
                final_chunk_len=self._final_chunk_len,
                blocks_digest=self._digest.digest(),
            ).seal()
            self._emit(trailer)
            self._emit(trailer)
            self._emit(self._sealed_header)
            flush = getattr(self._sink, "flush", None)
            if callable(flush):
                flush()
        except BaseException:
            self.abort()
            raise
        self._closed = True
        self._shutdown()
        self._summary = StreamSummary(
            container_bytes=self._container_bytes,
            plaintext_bytes=self._plaintext_bytes,
            blocks=self._next_index,
            block_size=self.layout.block_size,
            nsym=self.layout.nsym,
            interleave=self.layout.interleave,
            slot_size=self.layout.slot_size,
            sha256=self._sha256.hexdigest(),
            correctable_bytes_per_codeword=self.layout.nsym // 2,
            burst_tolerance_bytes=self.layout.burst_tolerance(self._next_index),
        )
        return self._summary

    def abort(self) -> None:
        self._closed = True
        self._batch = []
        self._window.clear()
        self._pending = bytearray()
        self._shutdown()

    def _shutdown(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=True)
            self._pool = None

    def _ensure_open(self) -> None:
        if self._closed:
            raise ValueError("This StreamWriter is closed.")

    def _emit(self, data: bytes) -> None:
        self._sink.write(data)
        self._sha256.update(data)
        self._container_bytes += len(data)

    def _queue(self, chunk: bytes) -> None:
        self._batch.append(chunk)
        if len(self._batch) >= BATCH_BLOCKS * self._workers:
            self._flush(final=False)

    def _flush(self, *, final: bool) -> None:
        if not self._batch:
            return
        first = self._next_index
        if first + len(self._batch) > MAX_BLOCKS:
            raise ContainerError("The stream exceeds the largest block count a container holds.")
        final_index = first + len(self._batch) - 1 if final else None
        jobs = [(first + offset, chunk) for offset, chunk in enumerate(self._batch)]
        self._batch = []
        self._next_index += len(jobs)
        groups = [jobs[start : start + BATCH_BLOCKS] for start in range(0, len(jobs), BATCH_BLOCKS)]
        if self._pool is not None and len(groups) > 1:
            encoded_groups = list(
                self._pool.map(lambda group: self._encode(group, final_index), groups)
            )
        else:
            encoded_groups = [self._encode(group, final_index) for group in groups]
        for slots in encoded_groups:
            for slot in slots:
                self._place(slot)

    def _encode(self, jobs: list, final_index: int | None) -> list[bytes]:
        cipher = ChunkCipher(self._data_key, self.header.nonce_prefix, self._sealed_header)
        block_size = self.layout.block_size
        blocks = []
        for index, chunk in jobs:
            final = index == final_index
            sealed = cipher.seal(index, chunk, final=final)
            block = DESCRIPTOR.pack(index, len(sealed), FINAL_FLAG if final else 0) + sealed
            blocks.append(block + bytes(block_size - len(block)))
        container_id = self.header.container_id
        return [
            encoded + _slot_tag(container_id, encoded)
            for encoded in rs.encode_many(blocks, self.layout.nsym)
        ]

    def _place(self, slot: bytes) -> None:
        self._emit(slot)
        self._digest.update(slot[-SLOT_TAG_SIZE:])
        self._window.append(slot)
        if len(self._window) > self.layout.interleave:
            self._emit(self._window.popleft())


@dataclass
class _Block:
    data: bytes
    chunk_len: int
    tag: bytes


class StreamReader:
    def __init__(self, source, passphrase=None):
        self._source = as_source(source)
        self._metadata_damaged: list[str] = []
        self.header = self._locate_header()
        self.layout = self.header.layout
        self._cipher = None
        if passphrase is not None:
            kek = derive_key(_as_bytes(passphrase), self.header.salt, self.header.kdf_params)
            data_key = unwrap_key(
                kek, self.header.wrap_nonce, self.header.wrapped_key, self.header.key_binding()
            )
            self._cipher = ChunkCipher(data_key, self.header.nonce_prefix, self.header.seal())
        self.trailer, self.blocks = self._locate_end()
        self.report = self._fresh_report()

    @property
    def format_version(self) -> int:
        return FORMAT_VERSION

    @property
    def flags(self) -> int:
        return self.header.flags

    @property
    def plaintext_bytes(self) -> int | None:
        return self.trailer.plaintext_bytes if self.trailer is not None else None

    def __iter__(self):
        return self.chunks()

    def chunks(self):
        if self._cipher is None:
            raise ContainerError(
                "Decrypting needs the passphrase; this reader checks structure only."
            )
        last = self.blocks - 1
        for index, block in self._pass(check_spares=False):
            if block is None:
                raise CorruptionError(
                    f"Block {index} is damaged beyond repair: {self.report.summary()}",
                    self.report,
                )
            ciphertext = block.data[DESCRIPTOR.size : DESCRIPTOR.size + block.chunk_len]
            try:
                plaintext = self._cipher.open(index, ciphertext, final=index == last)
            except CorruptionError as exc:
                self.report.failed_blocks.append(index)
                raise CorruptionError(str(exc), self.report) from exc
            self._discard_unverified(index)
            if plaintext:
                yield plaintext
        if not self.report.ok:
            raise CorruptionError(
                "Backup failed its final check: " + self.report.summary(), self.report
            )

    def read_all(self) -> bytes:
        return b"".join(self.chunks())

    def verify(self) -> StreamRepairReport:
        last = self.blocks - 1
        for index, block in self._pass(check_spares=True):
            if block is None or self._cipher is None:
                continue
            ciphertext = block.data[DESCRIPTOR.size : DESCRIPTOR.size + block.chunk_len]
            try:
                self._cipher.open(index, ciphertext, final=index == last)
            except CorruptionError:
                self.report.failed_blocks.append(index)
                continue
            self._discard_unverified(index)
        return self.report

    def _discard_unverified(self, index: int) -> None:
        if index in self.report.unverified_blocks:
            self.report.unverified_blocks.remove(index)

    def _fresh_report(self) -> StreamRepairReport:
        return StreamRepairReport(
            total_blocks=self.blocks, metadata_damaged=list(self._metadata_damaged)
        )

    def _locate_header(self) -> StreamHeader:
        size = self._source.size
        offsets = [0]
        if size >= 2 * HEADER_SIZE:
            offsets.append(size - HEADER_SIZE)
        copies = []
        for offset in offsets:
            raw = self._source.read_at(offset, HEADER_SIZE)
            opened = open_sealed_header(raw)
            verified = opened is not None and opened[0] == FORMAT_VERSION
            copies.append(raw if verified else None)
        chosen = next((raw for raw in copies if raw is not None), None)
        if chosen is None:
            found = first_verified_header(self._source)
            if found is not None and found.version == V1_FORMAT_VERSION:
                raise ContainerError(
                    "This is a format version 1 container; read it with read_container."
                )
            if found is not None:
                raise ContainerError(unsupported_version_message(found.version))
            raise ContainerError(
                "Not a DBS container, or every copy of its header is destroyed."
            )
        header = StreamHeader.parse(open_sealed_header(chosen)[1])
        names = ("front header", "back header")
        for name, raw in zip(names, copies + [None] * (2 - len(copies))):
            if raw != chosen:
                self._metadata_damaged.append(name)
        return header

    def _locate_end(self) -> tuple[StreamTrailer | None, int]:
        size = self._source.size
        end = size - HEADER_SIZE - 2 * TRAILER_SIZE
        trailer, damaged = self._read_trailers(
            end, lambda found: self.layout.container_size(found.blocks) == size
        )
        if trailer is None:
            count = self._scan_block_count()
            start = HEADER_SIZE + 2 * count * self.layout.slot_size
            trailer, damaged = self._read_trailers(start, lambda found: found.blocks == count)
        else:
            count = trailer.blocks
        if trailer is None:
            damaged = ["trailer (both copies)"]
        self._metadata_damaged.extend(damaged)
        return trailer, count

    def _read_trailers(self, start: int, consistent) -> tuple[StreamTrailer | None, list[str]]:
        if start < HEADER_SIZE:
            return None, []
        found = []
        for number in (1, 2):
            raw = self._source.read_at(start + (number - 1) * TRAILER_SIZE, TRAILER_SIZE)
            trailer = StreamTrailer.open(raw, self.header)
            found.append(trailer if trailer is not None and consistent(trailer) else None)
        chosen = next((trailer for trailer in found if trailer is not None), None)
        if chosen is None:
            return None, []
        damaged = [
            f"trailer copy {number}"
            for number, trailer in zip((1, 2), found)
            if trailer != chosen
        ]
        return chosen, damaged

    def _first_descriptors(self, offsets: list[int]) -> list[tuple[int, int] | None]:
        nsym = self.layout.nsym
        size = rs.CODEWORD_SIZE
        codewords = [self._source.read_at(offset, size) for offset in offsets]
        joined = b"".join(codeword for codeword in codewords if len(codeword) == size)
        damaged = set(rs.damaged_codewords(joined, nsym) or []) if joined else set()
        descriptors = []
        number = 0
        for codeword in codewords:
            if len(codeword) != size:
                descriptors.append(None)
                continue
            if number in damaged:
                message = rs.decode_codeword(codeword, nsym)
            else:
                message = codeword[: size - nsym]
            number += 1
            descriptors.append(self._descriptor_of(message))
        return descriptors

    @staticmethod
    def _descriptor_of(message: bytes | None) -> tuple[int, int] | None:
        if message is None or len(message) < DESCRIPTOR.size:
            return None
        index, _chunk_len, flags = DESCRIPTOR.unpack_from(message)
        if flags & ~FINAL_FLAG or message[13:16] != _ZERO_RESERVED:
            return None
        return index, flags

    def _scan_block_count(self) -> int:
        slot_size = self.layout.slot_size
        interleave = self.layout.interleave
        size = self._source.size
        index = 0
        while index < MAX_BLOCKS:
            batch = []
            for candidate in range(index, min(index + SCAN_BATCH_BLOCKS, MAX_BLOCKS)):
                position = first_copy_position(candidate, interleave)
                offset = HEADER_SIZE + position * slot_size
                if offset >= size:
                    break
                batch.append((candidate, position, offset))
            if not batch:
                break
            descriptors = self._first_descriptors([offset for _, _, offset in batch])
            for (candidate, position, _offset), descriptor in zip(batch, descriptors):
                if descriptor is None:
                    continue
                found, flags = descriptor
                if found == candidate and flags & FINAL_FLAG:
                    return candidate + 1
                if found < candidate:
                    count = position - found
                    if 0 < count <= candidate and count - interleave <= found < count:
                        return count
            index = batch[-1][0] + 1
        raise CorruptionError(
            "The backup is cut short before its last block, so its end cannot be found.",
            StreamRepairReport(problems=["the end of the backup is missing"]),
        )

    def _slots(self):
        slot_size = self.layout.slot_size
        positions = 2 * self.blocks
        for start in range(0, positions, READ_BATCH_SLOTS):
            count = min(READ_BATCH_SLOTS, positions - start)
            raw = self._source.read_at(HEADER_SIZE + start * slot_size, count * slot_size)
            for number in range(count):
                yield raw[number * slot_size : (number + 1) * slot_size]

    def _chunk_len(self, data: bytes, index: int) -> int | None:
        layout = self.layout
        if len(data) != layout.block_size:
            return None
        found, chunk_len, flags = DESCRIPTOR.unpack_from(data)
        final = index == self.blocks - 1
        if found != index or flags != (FINAL_FLAG if final else 0):
            return None
        if data[13:16] != _ZERO_RESERVED:
            return None
        if not final:
            return chunk_len if chunk_len == layout.max_chunk_len else None
        if not TAG_LENGTH <= chunk_len <= layout.max_chunk_len:
            return None
        if self.trailer is not None and chunk_len != self.trailer.final_chunk_len:
            return None
        end = DESCRIPTOR.size + chunk_len
        if data[end:] != bytes(layout.block_size - end):
            return None
        return chunk_len

    def _clean(self, raw: bytes, index: int) -> _Block | None:
        encoded_size = self.layout.encoded_size
        if len(raw) != self.layout.slot_size:
            return None
        encoded = raw[:encoded_size]
        tag = raw[encoded_size:]
        if _slot_tag(self.header.container_id, encoded) != tag:
            return None
        data = rs.strip_parity(encoded, self.layout.nsym)
        if data is None:
            return None
        chunk_len = self._chunk_len(data, index)
        if chunk_len is None:
            return None
        return _Block(data, chunk_len, tag)

    def _repair(self, index: int, first: bytes | None, second: bytes | None) -> _Block | None:
        report = self.report
        if second is not None:
            block = self._clean(second, index)
            if block is not None:
                report.blocks_used_b += 1
                return block
        layout = self.layout
        copies = [raw for raw in (first, second) if raw is not None]
        labels = [label for label, raw in (("a", first), ("b", second)) if raw is not None]
        if not copies:
            return None
        data, used, decoded = rs.repair_from_copies(
            [raw[: layout.encoded_size] for raw in copies], layout.nsym
        )
        if data is None:
            return None
        chunk_len = self._chunk_len(data, index)
        if chunk_len is None:
            return None
        tag = _slot_tag(self.header.container_id, rs.encode(data, layout.nsym))
        stored = [raw[layout.encoded_size :] for raw in copies]
        if tag not in stored:
            if decoded or (len(stored) == 2 and stored[0] == stored[1]):
                return None
            report.unverified_blocks.append(index)
        sources = {labels[number] for number in used}
        if len(sources) > 1:
            report.blocks_merged += 1
        elif sources == {"b"}:
            report.blocks_used_b += 1
            if decoded:
                report.blocks_rs_corrected += 1
        else:
            report.blocks_rs_corrected += 1
        return _Block(data, chunk_len, tag)

    def _spare_intact(self, raw: bytes, tag: bytes | None) -> bool:
        encoded_size = self.layout.encoded_size
        if len(raw) != self.layout.slot_size or raw[encoded_size:] != tag:
            return False
        return _slot_tag(self.header.container_id, raw[:encoded_size]) == tag

    def _resolved(self, check_spares: bool):
        report = self.report
        slot_size = self.layout.slot_size
        waiting: dict[int, bytes | None] = {}
        ready: dict[int, _Block | None] = {}
        first_tags: dict[int, bytes] = {}
        next_index = 0
        for (_position, index, first_copy), raw in zip(
            schedule(self.blocks, self.layout.interleave), self._slots()
        ):
            complete = len(raw) == slot_size
            if not complete:
                report.copies_available = 1
            if first_copy:
                block = self._clean(raw, index) if complete else None
                if block is not None:
                    report.blocks_direct += 1
                    ready[index] = block
                    if check_spares:
                        first_tags[index] = block.tag
                else:
                    waiting[index] = raw if complete else None
            elif index in waiting:
                block = self._repair(index, waiting.pop(index), raw if complete else None)
                if block is None:
                    report.failed_blocks.append(index)
                ready[index] = block
            elif check_spares and not self._spare_intact(raw, first_tags.pop(index, None)):
                report.spares_damaged.append(index)
            while next_index in ready:
                yield next_index, ready.pop(next_index)
                next_index += 1
        for index in range(next_index, self.blocks):
            if index not in report.failed_blocks:
                report.failed_blocks.append(index)
            yield index, None

    def _pass(self, *, check_spares: bool):
        self.report = self._fresh_report()
        report = self.report
        digest = _blocks_digest(self.header.container_id)
        for index, block in self._resolved(check_spares):
            if block is not None:
                digest.update(block.tag)
            yield index, block
        if self.trailer is None or report.failed_blocks:
            return
        if digest.digest() == self.trailer.blocks_digest:
            report.unverified_blocks.clear()
        elif report.unverified_blocks:
            report.failed_blocks.extend(report.unverified_blocks)
            report.unverified_blocks.clear()
        else:
            report.problems.append("the trailer's digest of the block hashes does not match")
