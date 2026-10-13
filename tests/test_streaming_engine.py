import errno
import hashlib
import io
import json
import os
import threading
import tracemalloc
import zlib
from contextlib import contextmanager
from io import StringIO
from pathlib import Path

import pytest
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.db import DatabaseError

import dbs
from dbs import BackupRegistry, ModelBackup
from dbs.container import StreamReader, StreamWriter, read_format_version
from dbs.container.stream import HEADER_SIZE, schedule
from dbs.engine import backup as backup_engine
from dbs.engine import create_backup, frames, pipeline, restore_backup, validate_backup, write_backup
from dbs.engine.frames import PayloadReader
from dbs.exceptions import (
    BackupError,
    ContainerError,
    CorruptionError,
    MissingSourceFiles,
)
from dbs.files import SkippedFile
from dbs.serialize import AllRowsSerializer, RowLoader, serialize_batches
from tests.conftest import FAST_KDF
from tests.format1 import as_format1
from tests.testapp.models import Author, Book, Tag

PASS = "streaming-engine-pass-phrase"

BOOKS = 6


def _dbs_threads():
    return [thread.name for thread in threading.enumerate() if thread.name.startswith("dbs-")]


def _leftovers(directory):
    return [path.name for path in directory.iterdir() if path.name.startswith(".")]


@pytest.fixture
def library(db, tmp_path, settings):
    settings.DBS_RESTORE_ROOTS = [str(tmp_path)]
    sidecars = tmp_path / "sidecars"
    sidecars.mkdir()
    tags = [Tag.objects.create(label=f"tag {index}") for index in range(3)]
    books = []
    for index in range(BOOKS):
        author = Author.objects.create(name=f"Author {index}")
        sidecar = sidecars / f"book-{index}.dat"
        sidecar.write_bytes(os.urandom(1000 + index))
        book = Book.objects.create(title=f"Book {index}", author=author, sidecar_path=str(sidecar))
        book.tags.set(tags[: index % 4])
        book.cover.save(f"cover-{index}.bin", ContentFile(os.urandom(2000 + index)), save=True)
        books.append(book)
    return books


def _snapshot(books):
    return {
        book.title: (
            book.author.name,
            sorted(book.tags.values_list("label", flat=True)),
            book.cover.storage.open(book.cover.name, "rb").read(),
            open(book.sidecar_path, "rb").read(),
        )
        for book in books
    }


def _restored_snapshot():
    return _snapshot(Book.objects.order_by("title"))


def _wipe(books):
    for book in books:
        if book.cover.storage.exists(book.cover.name):
            book.cover.storage.delete(book.cover.name)
        if os.path.exists(book.sidecar_path):
            os.remove(book.sidecar_path)
    Book.objects.all().delete()
    Tag.objects.all().delete()
    Author.objects.all().delete()


def test_write_backup_is_public():
    assert dbs.write_backup is write_backup
    assert dbs.BackupSummary is backup_engine.BackupSummary


def test_write_backup_to_a_path_summarises_the_file(library, tmp_path):
    path = tmp_path / "nightly.dbs"

    summary = write_backup(path, PASS, kdf_params=FAST_KDF)

    data = path.read_bytes()
    assert summary.path == str(path) and summary.verified
    assert summary.format_version == read_format_version(data) == 2
    assert summary.bytes_written == len(data)
    assert summary.sha256 == hashlib.sha256(data).hexdigest()
    assert summary.records == BOOKS * 2 + 3
    assert summary.files == BOOKS * 2 and summary.skipped_files == []
    assert {"model": "testapp.book", "count": BOOKS} in summary.models
    assert summary.blocks >= 1 and summary.nsym == 16 and summary.interleave == 64
    assert summary.correctable_bytes_per_codeword == 8
    assert path.stat().st_mode & 0o777 == 0o600
    assert _leftovers(tmp_path) == []


def test_write_backup_to_a_file_object_verifies_it_in_place(library):
    buffer = io.BytesIO()
    buffer.write(b"lead")

    summary = write_backup(buffer, PASS, kdf_params=FAST_KDF)

    assert summary.verified and summary.path is None
    assert buffer.tell() == 4 + summary.bytes_written
    container = buffer.getvalue()[4:]
    assert hashlib.sha256(container).hexdigest() == summary.sha256


class WriteOnly:
    def __init__(self, fail_after=None):
        self.parts = []
        self.fail_after = fail_after
        self.writers = set()

    def write(self, data):
        self.writers.add(threading.current_thread().name)
        if self.fail_after is not None and sum(map(len, self.parts)) >= self.fail_after:
            raise OSError(errno.ENOSPC, "No space left on device")
        self.parts.append(bytes(data))
        return len(data)

    def getvalue(self):
        return b"".join(self.parts)


def test_a_sink_that_cannot_be_read_back_is_written_by_its_own_thread(library):
    sink = WriteOnly()

    summary = write_backup(sink, PASS, kdf_params=FAST_KDF)

    assert not summary.verified
    assert sink.writers == {"dbs-backup-sink"}
    checked = validate_backup(sink.getvalue(), PASS)
    assert checked.ok and checked.decrypted_ok
    assert _dbs_threads() == []


def test_create_backup_still_returns_the_bytes_it_wrote(library, tmp_path):
    path = tmp_path / "small.dbs"

    container = create_backup(PASS, kdf_params=FAST_KDF, output=str(path))

    assert container == path.read_bytes()
    assert read_format_version(container) == 2


@contextmanager
def _as_source(kind, container, tmp_path):
    if kind == "bytes":
        yield container
        return
    path = tmp_path / f"source-{kind}.dbs"
    path.write_bytes(container)
    if kind == "path":
        yield str(path)
        return
    with open(path, "rb") as handle:
        yield handle


@pytest.mark.parametrize("form", [2, 1])
@pytest.mark.parametrize("kind", ["bytes", "path", "file"])
def test_every_entry_point_reads_bytes_paths_and_files(library, tmp_path, committed, kind, form):
    before = _snapshot(library)
    container = create_backup(PASS, kdf_params=FAST_KDF)
    if form == 1:
        container = as_format1(container, PASS)

    with _as_source(kind, container, tmp_path) as source:
        checked = validate_backup(source, PASS)
        structure = validate_backup(source)
        _wipe(library)
        with committed():
            out = restore_backup(source, PASS)
        if kind == "file":
            assert source.tell() == 0

    assert checked.ok and checked.decrypted_ok and structure.ok
    assert checked.stats["records"] == out.records_loaded
    assert out.files_written == BOOKS * 2
    assert _restored_snapshot() == before
    assert _dbs_threads() == []


def test_a_dry_run_from_a_stream_stages_nothing_and_loads_nothing(library, tmp_path):
    container = create_backup(PASS, kdf_params=FAST_KDF)
    _wipe(library)

    out = restore_backup(container, PASS, dry_run=True)

    assert out.records_would_load == BOOKS * 2 + 3
    assert out.files_would_write == BOOKS * 2
    assert not Book.objects.exists()
    assert [path for path in tmp_path.rglob("*") if path.is_file()] == []


def test_files_only_and_rows_only_restores(library, tmp_path, committed):
    container = create_backup(PASS, kdf_params=FAST_KDF)
    _wipe(library)

    with committed():
        files_only = restore_backup(container, PASS, load_data=False)
    assert files_only.files_written == BOOKS * 2 and not Book.objects.exists()

    rows_only = restore_backup(container, PASS, write_files=False)
    assert rows_only.records_loaded == BOOKS * 2 + 3 and rows_only.files_written == 0


def test_corruption_across_many_blocks_is_healed(db, tmp_path, settings, committed):
    settings.DBS_RESTORE_ROOTS = [str(tmp_path)]
    big = tmp_path / "big.bin"
    big.write_bytes(os.urandom(3 * 1024 * 1024))
    Book.objects.create(title="Big", author=Author.objects.create(name="Ada"), sidecar_path=str(big))
    container = create_backup(PASS, kdf_params=FAST_KDF)
    reader = StreamReader(io.BytesIO(container))
    assert reader.blocks > 8
    slot = reader.layout.slot_size
    firsts = sorted(
        HEADER_SIZE + position * slot
        for position, _index, first in schedule(reader.blocks, reader.layout.interleave)
        if first
    )
    damaged = bytearray(container)
    start = firsts[3]
    damaged[start : start + 5 * slot] = os.urandom(5 * slot)
    big.unlink()
    Book.objects.all().delete()

    with committed():
        out = restore_backup(bytes(damaged), PASS)

    assert out.healed
    assert out.repair_report.blocks_used_b >= 5
    assert big.stat().st_size == 3 * 1024 * 1024


def _fail_after_first_model(monkeypatch):
    real = backup_engine.serialize_batches
    models = []

    def flaky(*args, **kwargs):
        models.append(args[0])
        if len(models) > 1:
            raise DatabaseError("the connection dropped")
        yield from real(*args, **kwargs)

    monkeypatch.setattr(backup_engine, "serialize_batches", flaky)


def _fail_reading_files(monkeypatch):
    real = backup_engine.read_chunks

    def unreadable(source, size):
        yield from real(source, 10)
        raise SkippedFile("unreadable: Input/output error")

    monkeypatch.setattr(backup_engine, "read_chunks", unreadable)


@contextmanager
def _full_disk_file(path, verify=None):
    with REAL_CREATE_NEW_FILE(path, verify) as handle:
        yield FullDisk(handle)


REAL_CREATE_NEW_FILE = backup_engine.create_new_file


class FullDisk:
    def __init__(self, handle):
        self.handle = handle
        self.written = 0

    def write(self, data):
        if self.written > 100_000:
            raise OSError(errno.ENOSPC, "No space left on device")
        self.written += len(data)
        return self.handle.write(data)

    def flush(self):
        self.handle.flush()


def _fail_writing(monkeypatch):
    monkeypatch.setattr(backup_engine, "create_new_file", _full_disk_file)


def _fail_encoding(monkeypatch):
    def broken(self, data):
        raise ContainerError("the encoder failed")

    monkeypatch.setattr(StreamWriter, "write", broken)


def _fail_compressing(monkeypatch):
    def broken(segment):
        raise zlib.error("deflate failed")

    monkeypatch.setattr(pipeline, "_deflate", broken)


@pytest.mark.parametrize(
    "inject, raised",
    [
        (_fail_after_first_model, DatabaseError),
        (_fail_reading_files, MissingSourceFiles),
        (_fail_writing, OSError),
        (_fail_encoding, ContainerError),
        (_fail_compressing, zlib.error),
    ],
)
def test_a_failing_stage_stops_the_backup_and_leaves_no_file(
    library, tmp_path, monkeypatch, inject, raised
):
    inject(monkeypatch)
    output = tmp_path / "out" / "failed.dbs"
    output.parent.mkdir()

    with pytest.raises(raised):
        write_backup(output, PASS, kdf_params=FAST_KDF)

    assert list(output.parent.iterdir()) == []
    assert _dbs_threads() == []


def test_a_sink_that_fails_stops_the_backup(library):
    sink = WriteOnly(fail_after=50_000)

    with pytest.raises(OSError):
        write_backup(sink, PASS, kdf_params=FAST_KDF)

    assert _dbs_threads() == []


def test_a_file_that_vanishes_mid_backup_is_listed_when_allowed(library, tmp_path, monkeypatch, committed):
    real = backup_engine.read_chunks
    gone = library[0].sidecar_path

    def vanished(source, size):
        if source.path == os.path.realpath(gone):
            raise SkippedFile("missing")
        yield from real(source, size)

    monkeypatch.setattr(backup_engine, "read_chunks", vanished)
    with pytest.raises(MissingSourceFiles):
        write_backup(tmp_path / "refused.dbs", PASS, kdf_params=FAST_KDF)
    assert not (tmp_path / "refused.dbs").exists()

    left_out = []
    summary = write_backup(
        tmp_path / "allowed.dbs",
        PASS,
        kdf_params=FAST_KDF,
        allow_missing_files=True,
        skipped_files=left_out,
    )
    assert summary.files == BOOKS * 2 - 1
    assert left_out == summary.skipped_files and gone in left_out[0]

    _wipe(library)
    with committed():
        out = restore_backup(tmp_path / "allowed.dbs", PASS)
    assert out.files_written == BOOKS * 2 - 1
    assert not os.path.exists(gone)


def _restore_fails_reading(monkeypatch, container):
    def broken(self, channel, start, end):
        raise OSError(errno.EIO, "Input/output error")

    monkeypatch.setattr(pipeline.PrefetchingSource, "_read_ahead", broken)
    return container, OSError


def _restore_fails_decoding(monkeypatch, container):
    reader = StreamReader(io.BytesIO(container))
    slot = reader.layout.slot_size
    damaged = bytearray(container)
    last = reader.blocks - 1
    for position, index, _first in schedule(reader.blocks, reader.layout.interleave):
        if index == last:
            offset = HEADER_SIZE + position * slot
            damaged[offset : offset + slot] = bytes(slot)
    return bytes(damaged), CorruptionError


def _restore_fails_loading(monkeypatch, container):
    def fail(self, records):
        raise DatabaseError("the database went away")

    monkeypatch.setattr(RowLoader, "save", fail)
    return container, DatabaseError


@pytest.mark.parametrize(
    "inject", [_restore_fails_reading, _restore_fails_decoding, _restore_fails_loading]
)
def test_a_failing_stage_stops_the_restore_and_changes_nothing(library, tmp_path, monkeypatch, inject):
    container = create_backup(PASS, kdf_params=FAST_KDF)
    _wipe(library)
    path = tmp_path / "restore.dbs"
    container, raised = inject(monkeypatch, container)
    path.write_bytes(container)

    with pytest.raises(raised):
        restore_backup(str(path), PASS)

    assert not Book.objects.exists() and not Author.objects.exists()
    assert [item for item in tmp_path.rglob("*") if item.name.endswith(".dbs-restore")] == []
    assert not any((tmp_path / "sidecars").iterdir())
    assert _dbs_threads() == []


def test_unknown_payload_flags_are_refused(db):
    sink = io.BytesIO()
    with StreamWriter(sink, PASS, kdf_params=FAST_KDF, flags=1 << 15) as writer:
        writer.write(frames.PAYLOAD_MAGIC)

    with pytest.raises(ContainerError, match="newer DBS"):
        restore_backup(sink.getvalue(), PASS)


def test_the_backup_command_writes_format_2(library, tmp_path):
    output = tmp_path / "command.dbs"

    call_command(
        "dbs", "backup", str(output), passphrase=PASS, kdf_time=1, kdf_memory=8192, stdout=StringIO()
    )

    assert read_format_version(output.read_bytes()) == 2


def test_a_large_block_size_narrows_the_interleave_to_fit(library):
    summary = write_backup(io.BytesIO(), PASS, kdf_params=FAST_KDF, block_size=1024 * 1024)

    assert summary.block_size == 1024 * 1024
    assert 1 <= summary.interleave < 64

    with pytest.raises(BackupError, match="block_size"):
        write_backup(io.BytesIO(), PASS, kdf_params=FAST_KDF, block_size=100)


def test_batched_many_to_many_members_match_the_one_row_path(library):
    batched = [
        record
        for body, _count in serialize_batches(Book, ModelBackup(), set(), frozenset(), "default", rows=4)
        for record in json.loads(body)
    ]
    one_by_one = json.loads(
        AllRowsSerializer().serialize(Book.objects.order_by("pk"), use_natural_foreign_keys=False)
    )

    assert batched == one_by_one
    assert any(len(record["fields"]["tags"]) > 1 for record in batched)


def test_a_row_too_large_for_a_frame_is_refused_and_batches_split(db):
    Author.objects.create(name="a" * 300)
    Author.objects.create(name="b" * 300)

    split = list(serialize_batches(Author, ModelBackup(), set(), frozenset(), "default", limit=500))
    assert [count for _body, count in split] == [1, 1]

    Author.objects.create(name="c" * 1000)
    with pytest.raises(BackupError, match="above the 500 byte limit"):
        list(serialize_batches(Author, ModelBackup(), set(), frozenset(), "default", limit=500))


def _payload(*parts, magic=frames.PAYLOAD_MAGIC):
    data = magic + b"".join(parts)
    return [data[start : start + 7] for start in range(0, len(data), 7)]


HEADER = frames.json_frame(
    frames.HEADER, {"version": 2, "created": None, "django_version": "5", "order": ["a.one", "a.two"]}
)

TRAILER = frames.json_frame(
    frames.TRAILER, {"stats": {"models": [], "records": 0, "files": 0, "skipped_files": []}}
)


def _walk(pieces):
    reader = PayloadReader(pieces)
    reader.read_header()
    reader.read_manifest()
    for stream in reader.files():
        stream.drain()
    for _batch in reader.record_batches():
        pass
    reader.read_trailer()
    reader.finish()
    return reader


def test_a_well_formed_payload_reads_through():
    record = {"model": "a.one", "pk": 1, "fields": {}}
    entry = {"kind": "root", "size": 3, "model": None, "pk": None, "field": None, "name": "x", "root": "/r"}
    reader = _walk(
        _payload(
            HEADER,
            frames.json_frame(frames.MANIFEST, [entry]),
            frames.file_data_frame(0, b"abc"),
            frames.file_end_frame(0, size=3, sha256=hashlib.sha256(b"abc").hexdigest()),
            frames.json_frame(frames.RECORDS, [record]),
            TRAILER,
        )
    )
    assert reader.entries[0].sha256 == hashlib.sha256(b"abc").hexdigest()


@pytest.mark.parametrize(
    "pieces, problem",
    [
        (_payload(HEADER, TRAILER, magic=b"DBSPAY99"), "not a format version 2 payload"),
        (_payload(HEADER, frames.FRAME_PREFIX.pack(frames.RECORDS, frames.MAX_FRAME_BYTES + 1)), "claims"),
        (_payload(HEADER, frames.FRAME_PREFIX.pack(0x7A, 1) + b"x", TRAILER), "unknown frame kind"),
        (_payload(HEADER, frames.FRAME_PREFIX.pack(frames.RECORDS, 50) + b"[]"), "middle of a frame"),
        (_payload(HEADER), "ends before its trailer"),
        (_payload(HEADER, TRAILER, TRAILER), "data follows its trailer"),
        (_payload(frames.json_frame(frames.HEADER, {"version": 3, "order": []}), TRAILER), "version 2"),
        (
            _payload(
                HEADER,
                frames.json_frame(frames.RECORDS, [{"model": "a.two", "pk": 1, "fields": {}}]),
                frames.json_frame(frames.RECORDS, [{"model": "a.one", "pk": 1, "fields": {}}]),
                TRAILER,
            ),
            "out of the recorded model order",
        ),
        (
            _payload(
                HEADER,
                frames.json_frame(frames.RECORDS, [{"model": "evil.model", "pk": 1, "fields": {}}]),
                TRAILER,
            ),
            "outside the model order",
        ),
        (_payload(HEADER, frames.json_frame(frames.MANIFEST, [{"kind": "root"}]), TRAILER), "no kind or name"),
        (_payload(HEADER, frames.frame(frames.RECORDS, b"{not json"), TRAILER), "not valid JSON"),
        (
            _payload(
                HEADER,
                frames.json_frame(
                    frames.MANIFEST,
                    [{"kind": "root", "size": 1, "pk": None, "name": "x", "root": "/r"}],
                ),
                frames.file_data_frame(5, b"a"),
            ),
            "out of manifest order",
        ),
    ],
)
def test_a_malformed_payload_is_refused(pieces, problem):
    with pytest.raises(ContainerError, match=problem):
        _walk(pieces)


def test_a_file_whose_bytes_do_not_match_its_digest_is_refused():
    entry = {"kind": "root", "size": 3, "pk": None, "name": "x", "root": "/r"}
    pieces = _payload(
        HEADER,
        frames.json_frame(frames.MANIFEST, [entry]),
        frames.file_data_frame(0, b"abd"),
        frames.file_end_frame(0, size=3, sha256=hashlib.sha256(b"abc").hexdigest()),
        TRAILER,
    )
    with pytest.raises(CorruptionError, match="integrity hash"):
        _walk(pieces)


def _peak(action):
    tracemalloc.start()
    try:
        action()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


@pytest.mark.parametrize(
    "rows, mebibytes, budget",
    [
        (1000, 40, 32),
        pytest.param(
            50_000,
            100,
            64,
            marks=pytest.mark.skipif(
                not os.environ.get("DBS_SLOW_TESTS"), reason="set DBS_SLOW_TESTS=1"
            ),
        ),
    ],
)
def test_backup_and_restore_memory_stays_bounded(db, tmp_path, settings, committed, rows, mebibytes, budget):
    assets = tmp_path / "assets"
    assets.mkdir()
    for index in range(mebibytes // 4):
        (assets / f"part-{index}.bin").write_bytes(os.urandom(4 * 1024 * 1024))

    class Assets(ModelBackup):
        file_roots = [str(assets)]

    registry = BackupRegistry()
    registry.register(Author)(Assets)
    registry.register(Book)
    authors = Author.objects.bulk_create(Author(name=f"author {index}") for index in range(rows))
    Book.objects.bulk_create(
        Book(title=f"book {index}", author_id=authors[index].pk) for index in range(rows)
    )
    settings.DBS_RESTORE_ROOTS = [str(assets)]
    output = tmp_path / "large.dbs"
    summaries = []

    backup_peak = _peak(
        lambda: summaries.append(write_backup(output, PASS, registry=registry, kdf_params=FAST_KDF))
    )
    assert summaries[0].payload_bytes > mebibytes * 1024 * 1024
    for part in assets.iterdir():
        part.unlink()
    Book.objects.all().delete()
    Author.objects.all().delete()

    results = []

    def restore():
        with committed():
            results.append(restore_backup(output, PASS, registry=registry))

    restore_peak = _peak(restore)

    assert results[0].records_loaded == 2 * rows
    assert results[0].files_written == mebibytes // 4
    assert backup_peak < budget * 1024 * 1024
    assert restore_peak < budget * 1024 * 1024


class _Counting(io.RawIOBase):
    def __init__(self):
        self.digest = hashlib.sha256()
        self.size = 0

    def writable(self):
        return True

    def write(self, data):
        self.digest.update(data)
        self.size += len(data)
        return len(data)


class _BinaryStdout:
    def __init__(self, buffer):
        self.buffer = buffer

    def write(self, text):
        pass

    def flush(self):
        pass


def _stream_from_the_command(output_dir):
    received = _Counting()
    errors = StringIO()
    call_command(
        "dbs_backup",
        "--stream",
        passphrase=PASS,
        kdf_time=1,
        kdf_memory=8192,
        output_dir=str(output_dir),
        stdout=_BinaryStdout(received),
        stderr=errors,
    )
    summary = json.loads(errors.getvalue().splitlines()[-1])
    assert summary["size"] == received.size
    assert summary["sha256"] == received.digest.hexdigest()
    return output_dir / summary["name"]


def _scheduled_run(output_dir):
    from dbs import schedule_runner

    plan = {
        "output_dir": str(output_dir),
        "prefix": "nightly",
        "keep": 5,
        "database": "default",
        "compress": True,
        "verify": True,
        "block_size": None,
        "kdf_params": FAST_KDF,
    }
    return Path(schedule_runner.run_cycle(PASS, plan))


@pytest.mark.parametrize("writer", [_stream_from_the_command, _scheduled_run])
def test_streamed_and_scheduled_backups_keep_memory_bounded(db, tmp_path, settings, writer):
    assets = tmp_path / "assets"
    assets.mkdir()
    for index in range(10):
        (assets / f"part-{index}.bin").write_bytes(os.urandom(4 * 1024 * 1024))
    settings.DBS_FILE_ROOTS = [str(assets)]
    output_dir = tmp_path / "kept"
    written = []

    peak = _peak(lambda: written.append(writer(output_dir)))

    [path] = written
    assert path.stat().st_size > 40 * 1024 * 1024
    assert [entry.name for entry in output_dir.iterdir()] == [path.name]
    assert peak < 32 * 1024 * 1024
    assert validate_backup(path).ok
