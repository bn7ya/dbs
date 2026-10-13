from __future__ import annotations

import hashlib
import os
import threading
import zlib
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

from ..container import StreamWriter
from ..container.sources import FileSource
from ..container.stream import HEADER_SIZE
from ..exceptions import CorruptionError
from .frames import PAYLOAD_COMPRESSED

CHANNEL_BYTES = 2 * 1024 * 1024

PIECE_BYTES = 1024 * 1024

COMPRESSION_LEVEL = 6

SEGMENT_BYTES = 1024 * 1024

COMPRESSION_WORKERS = max(1, min(4, (os.cpu_count() or 1) - 1))

_END = object()


class Stopped(Exception):
    pass


class Pipeline:
    def __init__(self, name: str):
        self.name = name
        self.failure: BaseException | None = None
        self._stopped = False
        self._lock = threading.Lock()
        self._channels: list = []
        self._threads: list = []

    @property
    def stopped(self) -> bool:
        return self._stopped

    def channel(self, capacity: int = CHANNEL_BYTES) -> "Channel":
        channel = Channel(self, capacity)
        self._channels.append(channel)
        return channel

    def start(self, stage: str, work, *args) -> None:
        thread = threading.Thread(
            target=self._run, args=(work, args), name=f"dbs-{self.name}-{stage}", daemon=True
        )
        self._threads.append(thread)
        thread.start()

    def _run(self, work, args) -> None:
        try:
            work(*args)
        except Stopped:
            pass
        except BaseException as exc:
            self.fail(exc)

    def fail(self, exc: BaseException) -> None:
        with self._lock:
            if self.failure is None:
                self.failure = exc
        self.stop()

    def stop(self) -> None:
        with self._lock:
            self._stopped = True
        for channel in self._channels:
            channel.wake()

    def join(self) -> None:
        for thread in self._threads:
            thread.join()

    def __enter__(self) -> "Pipeline":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if exc_type is not None:
            self.stop()
        self.join()
        if self.failure is not None and (exc_type is None or issubclass(exc_type, Stopped)):
            raise self.failure from None
        return False


class Channel:
    def __init__(self, pipeline: Pipeline, capacity: int):
        self._pipeline = pipeline
        self._capacity = capacity
        self._items: deque = deque()
        self._bytes = 0
        self._ready = threading.Condition()

    def wake(self) -> None:
        with self._ready:
            self._ready.notify_all()

    def put(self, item) -> None:
        size = len(item)
        with self._ready:
            while (
                self._items
                and self._bytes + size > self._capacity
                and not self._pipeline.stopped
            ):
                self._ready.wait()
            self._append(item, size)

    def close(self) -> None:
        with self._ready:
            self._append(_END, 0)

    def _append(self, item, size: int) -> None:
        if self._pipeline.stopped:
            raise Stopped
        self._items.append(item)
        self._bytes += size
        self._ready.notify_all()

    def get(self):
        with self._ready:
            while not self._items and not self._pipeline.stopped:
                self._ready.wait()
            if self._pipeline.stopped:
                raise Stopped
            item = self._items.popleft()
            if item is not _END:
                self._bytes -= len(item)
            self._ready.notify_all()
            return item

    def __iter__(self):
        while True:
            item = self.get()
            if item is _END:
                return
            yield item


class ChannelSink:
    def __init__(self, channel: Channel):
        self._channel = channel

    def write(self, data) -> int:
        self._channel.put(data)
        return len(data)

    def flush(self) -> None:
        pass


class PayloadStream:
    def __init__(self, frames: Channel):
        self._frames = frames
        self.digest = hashlib.sha256()
        self.payload_bytes = 0
        self.container = None

    def write(self, data: bytes) -> None:
        self._frames.put(data)


class Segment:
    def __init__(self, future, size: int):
        self._future = future
        self._size = size

    def __len__(self) -> int:
        return self._size

    def result(self) -> bytes:
        return self._future.result()


def _deflate(segment: bytes) -> bytes:
    compressor = zlib.compressobj(COMPRESSION_LEVEL)
    return compressor.compress(segment) + compressor.flush()


def _compress(frames: Channel, compressed: Channel, stream: PayloadStream, workers: int) -> None:
    pool = ThreadPoolExecutor(workers, thread_name_prefix="dbs-backup-deflate")
    try:
        pending = bytearray()
        for item in frames:
            stream.digest.update(item)
            stream.payload_bytes += len(item)
            pending += item
            if len(pending) >= SEGMENT_BYTES:
                compressed.put(Segment(pool.submit(_deflate, bytes(pending)), len(pending)))
                pending = bytearray()
        if pending:
            compressed.put(Segment(pool.submit(_deflate, bytes(pending)), len(pending)))
        compressed.close()
    except BaseException:
        pool.shutdown(wait=True, cancel_futures=True)
        raise
    pool.shutdown(wait=True)


def _pass_through(frames: Channel, compressed: Channel, stream: PayloadStream) -> None:
    for item in frames:
        stream.digest.update(item)
        stream.payload_bytes += len(item)
        compressed.put(item)
    compressed.close()


def _encode(compressed: Channel, writer: StreamWriter, encoded: Channel, stream: PayloadStream) -> None:
    try:
        for item in compressed:
            writer.write(item.result() if isinstance(item, Segment) else item)
        stream.container = writer.close()
    except BaseException:
        writer.abort()
        raise
    encoded.close()


def _sink(encoded: Channel, output) -> None:
    for item in encoded:
        output.write(item)
    flush = getattr(output, "flush", None)
    if callable(flush):
        flush()


@contextmanager
def encoding(output, passphrase, *, compress: bool, **writer_options):
    pipeline = Pipeline("backup")
    frames = pipeline.channel()
    compressed = pipeline.channel()
    encoded = pipeline.channel()
    flags = PAYLOAD_COMPRESSED if compress else 0
    writer = StreamWriter(ChannelSink(encoded), passphrase, flags=flags, **writer_options)
    stream = PayloadStream(frames)
    with pipeline:
        pipeline.start("sink", _sink, encoded, output)
        pipeline.start("encode", _encode, compressed, writer, encoded, stream)
        if compress:
            pipeline.start("compress", _compress, frames, compressed, stream, COMPRESSION_WORKERS)
        else:
            pipeline.start("compress", _pass_through, frames, compressed, stream)
        yield stream
        frames.close()


class PrefetchingSource(FileSource):
    def __init__(self, fileobj):
        super().__init__(fileobj)
        self._lock = threading.Lock()
        self._pieces = None
        self._position = 0
        self._pending = memoryview(b"")

    def prefetch(self, pipeline: Pipeline, start: int, end: int) -> None:
        channel = pipeline.channel()
        self._pieces = iter(channel)
        self._position = start
        pipeline.start("read", self._read_ahead, channel, start, min(end, self.size))

    def _read_ahead(self, channel: Channel, start: int, end: int) -> None:
        offset = start
        while offset < end:
            with self._lock:
                piece = FileSource.read_at(self, offset, min(PIECE_BYTES, end - offset))
            if not piece:
                break
            channel.put(piece)
            offset += len(piece)
        channel.close()

    def read_at(self, offset: int, length: int) -> bytes:
        if self._pieces is not None and offset == self._position and length > 0:
            return self._take(length)
        with self._lock:
            return FileSource.read_at(self, offset, length)

    def _take(self, length: int) -> bytes:
        parts = []
        needed = length
        while needed:
            if not self._pending:
                self._pending = memoryview(next(self._pieces, b""))
                if not self._pending:
                    self._pieces = None
                    break
            part = self._pending[:needed]
            self._pending = self._pending[len(part) :]
            parts.append(part)
            needed -= len(part)
        taken = b"".join(parts)
        self._position += len(taken)
        return taken


class Inflater:
    def __init__(self, pieces: Channel):
        self._pieces = pieces
        self._member = zlib.decompressobj()
        self._started = False

    def feed(self, data: bytes) -> None:
        while data:
            self._started = True
            out = self._member.decompress(data, PIECE_BYTES)
            if out:
                self._pieces.put(out)
            if self._member.eof:
                data = self._member.unused_data
                self._member = zlib.decompressobj()
                self._started = False
            else:
                data = self._member.unconsumed_tail
                if not data:
                    self._drain()

    def _drain(self) -> None:
        while True:
            out = self._member.decompress(b"", PIECE_BYTES)
            if not out:
                return
            self._pieces.put(out)

    def finish(self) -> None:
        if self._started and not self._member.eof:
            raise CorruptionError("The compressed payload ends early.")


def _decode(reader, pieces: Channel, check_spares: bool) -> None:
    inflater = Inflater(pieces) if reader.flags & PAYLOAD_COMPRESSED else None
    for chunk in reader.chunks(check_spares=check_spares):
        if inflater is None:
            pieces.put(chunk)
        else:
            inflater.feed(chunk)
    if inflater is not None:
        inflater.finish()
    pieces.close()


@contextmanager
def decoding(reader, source=None, *, check_spares: bool = False):
    pipeline = Pipeline("restore")
    pieces = pipeline.channel()
    with pipeline:
        if isinstance(source, PrefetchingSource):
            end = HEADER_SIZE + 2 * reader.blocks * reader.layout.slot_size
            source.prefetch(pipeline, HEADER_SIZE, end)
        pipeline.start("decode", _decode, reader, pieces, check_spares)
        yield iter(pieces)
        pipeline.stop()
