from __future__ import annotations

import hashlib
import json
import struct

from ..exceptions import ContainerError, CorruptionError
from ..files import FileEntry

PAYLOAD_MAGIC = b"DBSPAY02"

PAYLOAD_VERSION = 2

PAYLOAD_COMPRESSED = 1 << 0

KNOWN_FLAGS = PAYLOAD_COMPRESSED

FRAME_PREFIX = struct.Struct(">BI")

FILE_INDEX = struct.Struct(">I")

HEADER = ord("H")
MANIFEST = ord("M")
FILE_DATA = ord("D")
FILE_END = ord("E")
RECORDS = ord("R")
TRAILER = ord("T")

KIND_NAMES = {
    HEADER: "header",
    MANIFEST: "file manifest",
    FILE_DATA: "file data",
    FILE_END: "file end",
    RECORDS: "records",
    TRAILER: "trailer",
}

MAX_FRAME_BYTES = 256 * 1024 * 1024

MAX_FILES = (1 << 32) - 1

FILE_CHUNK_BYTES = 1024 * 1024

MANIFEST_BATCH = 1000

ENTRY_KINDS = ("storage", "path", "root")

_SCALARS = (str, int, float, bool, type(None))


def frame(kind: int, body: bytes) -> bytes:
    if len(body) > MAX_FRAME_BYTES:
        raise ValueError(f"A {KIND_NAMES[kind]} frame of {len(body)} bytes is above the limit.")
    return FRAME_PREFIX.pack(kind, len(body)) + body


def json_bytes(value) -> bytes:
    return json.dumps(value, separators=(",", ":"), default=str).encode("utf-8")


def json_frame(kind: int, value) -> bytes:
    return frame(kind, json_bytes(value))


def manifest_item(entry: FileEntry) -> dict:
    return {
        "kind": entry.kind,
        "size": entry.size,
        "model": entry.model,
        "pk": entry.pk,
        "field": entry.field,
        "name": entry.name,
        "root": entry.root,
    }


def file_data_frame(index: int, chunk: bytes) -> bytes:
    return frame(FILE_DATA, FILE_INDEX.pack(index) + chunk)


def file_end_frame(index: int, *, size: int = 0, sha256: str = "", skipped: str = "") -> bytes:
    if skipped:
        return json_frame(FILE_END, {"index": index, "skipped": skipped})
    return json_frame(FILE_END, {"index": index, "size": size, "sha256": sha256})


def malformed(problem: str) -> ContainerError:
    return ContainerError(f"The backup's payload is malformed: {problem}.")


def _parsed(body: bytes, what: str):
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise malformed(f"its {what} is not valid JSON") from None


def _is_text(value) -> bool:
    return isinstance(value, str)


def _optional_text(value) -> bool:
    return value is None or isinstance(value, str)


def _count(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def checked_header(value) -> dict:
    if not isinstance(value, dict) or value.get("version") != PAYLOAD_VERSION:
        raise malformed("its header does not describe payload version 2")
    order = value.get("order")
    if not isinstance(order, list) or not all(_is_text(label) for label in order):
        raise malformed("its header does not list the model order")
    migrations = value.get("migrations")
    if migrations is not None and not (
        isinstance(migrations, dict)
        and all(_is_text(app) and _is_text(name) for app, name in migrations.items())
    ):
        raise malformed("its header records migrations in an unknown shape")
    for name in ("created", "django_version"):
        if not _optional_text(value.get(name)):
            raise malformed(f"its header's {name} is not text")
    return value


def checked_entry(value) -> FileEntry:
    if not isinstance(value, dict):
        raise malformed("a file manifest entry is not an object")
    if not _is_text(value.get("kind")) or not _is_text(value.get("name")):
        raise malformed("a file manifest entry has no kind or name")
    if not _count(value.get("size")):
        raise malformed("a file manifest entry has no valid size")
    for name in ("model", "field", "root"):
        if not _optional_text(value.get(name)):
            raise malformed(f"a file manifest entry's {name} is not text")
    if not isinstance(value.get("pk"), _SCALARS):
        raise malformed("a file manifest entry's primary key is not a plain value")
    return FileEntry(
        kind=value["kind"],
        size=value["size"],
        sha256="",
        model=value.get("model"),
        pk=value.get("pk"),
        field=value.get("field"),
        name=value["name"],
        root=value.get("root"),
    )


def checked_records(value, rank: dict, current: int) -> tuple[list, int]:
    if not isinstance(value, list):
        raise malformed("a records frame is not a list")
    for record in value:
        if not isinstance(record, dict) or not isinstance(record.get("fields"), dict):
            raise malformed("a record is not an object with fields")
        position = rank.get(record.get("model"))
        if position is None:
            raise malformed(f"a record belongs to {record.get('model')!r}, outside the model order")
        if position < current:
            raise malformed("records arrive out of the recorded model order")
        if not isinstance(record.get("pk"), _SCALARS):
            raise malformed("a record's primary key is not a plain value")
        current = position
    return value, current


def checked_trailer(value) -> dict:
    stats = value.get("stats") if isinstance(value, dict) else None
    if not isinstance(stats, dict):
        raise malformed("its trailer carries no statistics")
    models = stats.get("models")
    if not isinstance(models, list) or not all(
        isinstance(item, dict) and _is_text(item.get("model")) and _count(item.get("count"))
        for item in models
    ):
        raise malformed("its trailer lists models in an unknown shape")
    if not _count(stats.get("records")) or not _count(stats.get("files")):
        raise malformed("its trailer's counts are not numbers")
    skipped = stats.get("skipped_files")
    if not isinstance(skipped, list) or not all(_is_text(item) for item in skipped):
        raise malformed("its trailer lists skipped files in an unknown shape")
    return value


class FrameReader:
    def __init__(self, pieces):
        self._pieces = iter(pieces)
        self._buffer = bytearray()
        self._start = 0
        if self._take(len(PAYLOAD_MAGIC)) != PAYLOAD_MAGIC:
            raise ContainerError(
                "The decrypted payload is not a format version 2 payload."
            )

    def _available(self) -> int:
        return len(self._buffer) - self._start

    def _fill(self, size: int) -> bool:
        while self._available() < size:
            piece = next(self._pieces, None)
            if piece is None:
                return False
            if self._start:
                del self._buffer[: self._start]
                self._start = 0
            self._buffer += piece
        return True

    def _take(self, size: int) -> bytes:
        if not self._fill(size):
            raise malformed("it ends in the middle of a frame")
        taken = bytes(self._buffer[self._start : self._start + size])
        self._start += size
        return taken

    def next_frame(self) -> tuple[int, bytes] | None:
        if not self._fill(FRAME_PREFIX.size):
            if self._available():
                raise malformed("it ends in the middle of a frame")
            return None
        kind, length = FRAME_PREFIX.unpack_from(self._buffer, self._start)
        if kind not in KIND_NAMES:
            raise malformed(f"it holds an unknown frame kind {kind}")
        if length > MAX_FRAME_BYTES:
            raise malformed(f"a {KIND_NAMES[kind]} frame claims {length} bytes")
        self._start += FRAME_PREFIX.size
        return kind, self._take(length)


class FileStream:
    def __init__(self, reader: "PayloadReader", index: int, entry: FileEntry):
        self._reader = reader
        self.index = index
        self.entry = entry
        self.size = 0
        self.sha256 = ""
        self.skipped = ""
        self._done = False

    def chunks(self):
        digest = hashlib.sha256()
        size = 0
        while True:
            kind, body = self._reader._frame()
            if kind == FILE_DATA:
                if len(body) < FILE_INDEX.size or FILE_INDEX.unpack_from(body)[0] != self.index:
                    raise malformed("file data arrives out of manifest order")
                chunk = body[FILE_INDEX.size :]
                digest.update(chunk)
                size += len(chunk)
                yield chunk
                continue
            if kind != FILE_END:
                raise malformed(f"a {KIND_NAMES[kind]} frame interrupts a file's data")
            self._finish(_parsed(body, "file end"), size, digest.hexdigest())
            return

    def drain(self) -> None:
        for _chunk in self.chunks():
            pass

    def _finish(self, end, size: int, digest: str) -> None:
        if not isinstance(end, dict) or end.get("index") != self.index:
            raise malformed("a file's end does not match its data")
        self._done = True
        skipped = end.get("skipped")
        if skipped is not None:
            if not _is_text(skipped) or not skipped:
                raise malformed("a skipped file gives no reason")
            self.skipped = skipped
            return
        if not _count(end.get("size")) or not _is_text(end.get("sha256")):
            raise malformed("a file's end carries no size or digest")
        if size != end["size"] or digest != end["sha256"]:
            raise CorruptionError(
                f"File {self.entry.name!r} failed its integrity hash after extraction."
            )
        self.size = size
        self.sha256 = digest
        self.entry.sha256 = digest


class PayloadReader:
    def __init__(self, pieces):
        self._frames = FrameReader(pieces)
        self._pending: tuple[int, bytes] | None = None
        self.header: dict = {}
        self.entries: list[FileEntry] = []
        self.trailer: dict = {}
        self.rank: dict = {}
        self._position = 0
        self._phase = "header"

    def _frame(self) -> tuple[int, bytes]:
        found = self._peek()
        self._pending = None
        return found

    def _peek(self) -> tuple[int, bytes]:
        if self._pending is None:
            found = self._frames.next_frame()
            if found is None:
                raise malformed("it ends before its trailer")
            self._pending = found
        return self._pending

    def _expect(self, phase: str) -> None:
        if self._phase != phase:
            raise RuntimeError(f"The payload is read out of order: {phase} after {self._phase}.")

    def read_header(self) -> dict:
        self._expect("header")
        kind, body = self._frame()
        if kind != HEADER:
            raise malformed("it does not start with a header")
        self.header = checked_header(_parsed(body, "header"))
        self.rank = {label: position for position, label in enumerate(self.header["order"])}
        self._phase = "manifest"
        return self.header

    def read_manifest(self) -> list[FileEntry]:
        self._expect("manifest")
        while self._peek()[0] == MANIFEST:
            _kind, body = self._frame()
            items = _parsed(body, "file manifest")
            if not isinstance(items, list):
                raise malformed("a file manifest frame is not a list")
            self.entries.extend(checked_entry(item) for item in items)
            if len(self.entries) > MAX_FILES:
                raise malformed("its file manifest is too long")
        self._phase = "files"
        return self.entries

    def files(self):
        self._expect("files")
        for index, entry in enumerate(self.entries):
            stream = FileStream(self, index, entry)
            yield stream
            if not stream._done:
                stream.drain()
        self._phase = "records"

    def record_batches(self, *, parse: bool = True):
        self._expect("records")
        while self._peek()[0] == RECORDS:
            _kind, body = self._frame()
            if not parse:
                yield None
                continue
            records, self._position = checked_records(
                _parsed(body, "records"), self.rank, self._position
            )
            yield records
        self._phase = "trailer"

    def read_trailer(self) -> dict:
        self._expect("trailer")
        kind, body = self._frame()
        if kind != TRAILER:
            raise malformed(f"a {KIND_NAMES[kind]} frame comes where the trailer belongs")
        self.trailer = checked_trailer(_parsed(body, "trailer"))
        self._phase = "end"
        return self.trailer

    def finish(self) -> None:
        self._expect("end")
        if self._frames.next_frame() is not None:
            raise malformed("data follows its trailer")
        self._phase = "done"

    @property
    def stats(self) -> dict:
        return self.trailer.get("stats", {})
