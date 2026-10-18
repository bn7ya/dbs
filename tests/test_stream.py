"""Streaming container (format 2): round trips, repair, tamper detection, untrusted input, memory."""

import dataclasses
import hashlib
import io
import os
import random
import struct
import tracemalloc

import pytest

from dbs.container import (
    FORMAT_VERSION,
    StreamReader,
    StreamWriter,
    read_container,
    read_format_version,
)
from dbs.container.format import open_sealed_header, seal_header
from dbs.container.stream import (
    DESCRIPTOR,
    HEADER_BODY,
    HEADER_SIZE,
    TRAILER_SIZE,
    StreamHeader,
    StreamLayout,
    first_copy_position,
    schedule,
)
from dbs.crypto.kdf import KDFParams
from dbs.exceptions import ContainerError, CorruptionError, CryptoError, InvalidPassphrase

PASS = "stream-pass-phrase"
FAST = KDFParams(time_cost=1, memory_cost=8 * 1024, parallelism=1)
SMALL = {"block_size": 1024, "interleave": 4}


def write(data, *, pieces=None, **options):
    options = {"kdf_params": FAST, **options}
    sink = io.BytesIO()
    writer = StreamWriter(sink, PASS, **options)
    if pieces is None:
        writer.write(data)
    else:
        for start in range(0, len(data), pieces):
            writer.write(data[start : start + pieces])
    summary = writer.close()
    return sink.getvalue(), summary


def read(blob, passphrase=PASS):
    reader = StreamReader(io.BytesIO(blob), passphrase)
    return reader.read_all(), reader


def verify(blob, passphrase=None):
    return StreamReader(io.BytesIO(blob), passphrase).verify()


def slot_offsets(blob):
    reader = StreamReader(io.BytesIO(blob))
    slot = reader.layout.slot_size
    first, second = {}, {}
    for position, index, is_first in schedule(reader.blocks, reader.layout.interleave):
        (first if is_first else second)[index] = HEADER_SIZE + position * slot
    return first, second, slot


@pytest.fixture(scope="module")
def sample():
    data = os.urandom(40_000)
    blob, summary = write(data, **SMALL)
    return data, blob, summary


CAPACITY = 1024 - 32


@pytest.mark.parametrize(
    "size",
    [0, 1, CAPACITY - 1, CAPACITY, CAPACITY + 1, 3 * CAPACITY, 3 * CAPACITY + 1, 50_000],
)
@pytest.mark.parametrize("pieces", [None, 1, 333, CAPACITY, CAPACITY + 1])
def test_round_trips_across_sizes_and_write_patterns(size, pieces):
    if pieces == 1 and size > 4000:
        pytest.skip("byte-at-a-time writes are covered by the smaller sizes")
    data = os.urandom(size)
    blob, summary = write(data, pieces=pieces, **SMALL)
    out, reader = read(blob)
    assert out == data
    assert reader.plaintext_bytes == size == summary.plaintext_bytes
    assert summary.blocks == max(1, -(-size // CAPACITY)) == reader.blocks
    report = verify(blob)
    assert report.ok and not report.healed and report.blocks_direct == summary.blocks


def test_multi_mebibyte_round_trip_with_the_default_layout():
    data = os.urandom(3 * 1024 * 1024 + 12_345)
    blob, summary = write(data, pieces=1 << 20)
    out, reader = read(blob)
    assert out == data
    assert reader.layout == StreamLayout()
    assert summary.interleave == 64 and summary.nsym == 16


def test_the_summary_describes_the_written_bytes(sample):
    data, blob, summary = sample
    assert summary.container_bytes == len(blob)
    assert summary.sha256 == hashlib.sha256(blob).hexdigest()
    assert summary.plaintext_bytes == len(data)
    assert summary.correctable_bytes_per_codeword == 8
    assert summary.burst_tolerance_bytes == 4 * summary.slot_size
    assert len(blob) == StreamLayout(**SMALL).container_size(summary.blocks)


@pytest.mark.parametrize("workers", [1, 2, 3])
def test_worker_count_does_not_change_the_plaintext(workers):
    data = os.urandom(100_000)
    blob, _summary = write(data, workers=workers, **SMALL)
    assert read(blob)[0] == data


def test_the_format_version_is_two_and_readable_from_a_file(sample):
    _data, blob, _summary = sample
    assert FORMAT_VERSION == 2
    assert read_format_version(blob) == 2
    assert read_format_version(io.BytesIO(blob)) == 2


def test_the_v1_reader_and_the_stream_reader_refuse_each_other(sample):
    _data, blob, _summary = sample
    with pytest.raises(ContainerError, match="StreamReader"):
        read_container(blob)
    from tests.format1 import encode_copy, write_container

    encoded, plan = encode_copy(b"v1 payload")
    v1 = write_container(
        {"copy_len": plan.copy_len, "blocks": plan.to_dict()}, encoded, encoded, flags=0
    )
    with pytest.raises(ContainerError, match="version 1"):
        StreamReader(io.BytesIO(v1))


def test_a_wrong_passphrase_fails_before_any_plaintext(sample):
    _data, blob, _summary = sample
    with pytest.raises(InvalidPassphrase):
        StreamReader(io.BytesIO(blob), "not the passphrase")


def test_structure_checks_need_no_passphrase_but_decrypting_does(sample):
    _data, blob, _summary = sample
    reader = StreamReader(io.BytesIO(blob))
    assert reader.verify().ok
    with pytest.raises(ContainerError, match="passphrase"):
        list(reader.chunks())


def test_a_reader_can_be_read_twice(sample):
    data, blob, _summary = sample
    reader = StreamReader(io.BytesIO(blob), PASS)
    assert reader.read_all() == data
    assert reader.read_all() == data


def test_the_plaintext_is_not_visible_in_the_container():
    data = b"confidential-customer-name " * 400
    blob, _summary = write(data, **SMALL)
    assert b"confidential" not in blob
    assert hashlib.sha256(data).digest() not in blob
    assert hashlib.sha256(data).hexdigest().encode() not in blob


def test_flags_are_stored_and_authenticated():
    blob, _summary = write(b"x", flags=0x0101, **SMALL)
    assert StreamReader(io.BytesIO(blob)).flags == 0x0101


def test_every_byte_of_the_front_header_is_survivable(sample):
    data, blob, _summary = sample
    for offset in range(HEADER_SIZE):
        damaged = bytearray(blob)
        damaged[offset] ^= 0xFF
        out, reader = read(bytes(damaged))
        assert out == data, offset
        assert "front header" in reader.report.metadata_damaged
        assert read_format_version(bytes(damaged)) == 2


def test_every_byte_of_the_back_header_and_trailers_is_survivable(sample):
    data, blob, _summary = sample
    tail = HEADER_SIZE + 2 * TRAILER_SIZE
    for offset in range(len(blob) - tail, len(blob), 3):
        damaged = bytearray(blob)
        damaged[offset] ^= 0x5A
        out, reader = read(bytes(damaged))
        assert out == data, offset
        assert reader.report.healed


def test_both_trailers_lost_are_rebuilt_from_the_blocks(sample):
    data, blob, _summary = sample
    damaged = bytearray(blob)
    start = len(blob) - HEADER_SIZE - 2 * TRAILER_SIZE
    damaged[start : start + 2 * TRAILER_SIZE] = bytes(2 * TRAILER_SIZE)
    out, reader = read(bytes(damaged))
    assert out == data
    assert "trailer (both copies)" in reader.report.metadata_damaged
    assert verify(bytes(damaged)).ok


def test_both_header_copies_lost_is_unreadable(sample):
    _data, blob, _summary = sample
    damaged = bytearray(blob)
    damaged[20] ^= 1
    damaged[-20] ^= 1
    with pytest.raises(ContainerError, match="header"):
        StreamReader(io.BytesIO(bytes(damaged)), PASS)


def test_truncation_at_any_offset_never_yields_wrong_data(sample):
    data, blob, _summary = sample
    first, second, slot = slot_offsets(blob)
    last_first_copy_end = max(first.values()) + slot
    rng = random.Random(1)
    cuts = sorted(
        set(
            list(range(0, 400, 9))
            + [rng.randrange(len(blob)) for _ in range(40)]
            + list(range(len(blob) - 600, len(blob), 5))
            + [last_first_copy_end, last_first_copy_end - 1]
        )
    )
    survived = 0
    for cut in cuts:
        try:
            out, reader = read(blob[:cut])
        except InvalidPassphrase:
            pytest.fail(f"cut at {cut} reported a wrong passphrase")
        except ContainerError:
            assert cut < last_first_copy_end, cut
            continue
        assert out == data, cut
        assert reader.report.healed
        survived += 1
    assert survived > 100


def test_truncation_after_every_first_copy_keeps_the_backup(sample):
    data, blob, _summary = sample
    first, _second, slot = slot_offsets(blob)
    out, reader = read(blob[: max(first.values()) + slot])
    assert out == data
    assert reader.report.copies_available == 1
    assert "part of the second copy lost to truncation" in reader.report.summary()


def test_random_corruption_within_the_parity_budget_in_one_copy(sample):
    data, blob, _summary = sample
    first, _second, _slot = slot_offsets(blob)
    rng = random.Random(2)
    damaged = bytearray(blob)
    for offset in first.values():
        for codeword in rng.sample(range(4), 2):
            for position in rng.sample(range(255), 8):
                damaged[offset + codeword * 255 + position] ^= rng.randint(1, 255)
    out, reader = read(bytes(damaged))
    assert out == data
    report = verify(bytes(damaged))
    assert report.ok and report.healed and report.blocks_used_b == len(first)


def test_random_corruption_in_both_copies_is_repaired(sample):
    data, blob, _summary = sample
    first, second, _slot = slot_offsets(blob)
    rng = random.Random(3)
    damaged = bytearray(blob)
    for index in first:
        for offset in (first[index], second[index]):
            for position in rng.sample(range(255), 5):
                damaged[offset + 255 + position] ^= rng.randint(1, 255)
    out, _reader = read(bytes(damaged))
    assert out == data
    report = verify(bytes(damaged))
    assert report.ok and report.blocks_rs_corrected == len(first)


def test_damage_in_different_codewords_of_both_copies_is_rebuilt_from_both(sample):
    data, blob, _summary = sample
    first, second, _slot = slot_offsets(blob)
    damaged = bytearray(blob)
    damaged[first[3] + 10 : first[3] + 60] = bytes(50)
    damaged[second[3] + 600 : second[3] + 650] = bytes(50)
    assert read(bytes(damaged))[0] == data
    report = verify(bytes(damaged))
    assert report.blocks_merged == 1 and "rebuilt from both copies" in report.summary()


def test_a_whole_block_lost_in_one_copy_is_restored(sample):
    data, blob, _summary = sample
    first, second, slot = slot_offsets(blob)
    for copies in (first, second):
        damaged = bytearray(blob)
        damaged[copies[5] : copies[5] + slot] = bytes(slot)
        out, _reader = read(bytes(damaged))
        assert out == data
        report = verify(bytes(damaged))
        assert report.ok and report.healed
        if copies is second:
            assert report.spares_damaged == [5]


def test_reading_can_check_the_spare_copies_in_the_same_pass(sample):
    data, blob, _summary = sample
    _first, second, slot = slot_offsets(blob)
    damaged = bytearray(blob)
    damaged[second[5] : second[5] + slot] = bytes(slot)

    reader = StreamReader(io.BytesIO(bytes(damaged)), PASS)
    assert b"".join(reader.chunks(check_spares=True)) == data
    assert reader.report.spares_damaged == [5] and reader.report.healed

    plain = StreamReader(io.BytesIO(bytes(damaged)), PASS)
    assert b"".join(plain.chunks()) == data
    assert plain.report.spares_damaged == [] and not plain.report.healed


def test_a_burst_shorter_than_the_interleave_distance_is_survivable(sample):
    data, blob, summary = sample
    rng = random.Random(4)
    region_end = len(blob) - HEADER_SIZE - 2 * TRAILER_SIZE
    for _ in range(25):
        length = summary.burst_tolerance_bytes
        start = rng.randrange(HEADER_SIZE, region_end - length)
        damaged = bytearray(blob)
        damaged[start : start + length] = os.urandom(length)
        out, _reader = read(bytes(damaged))
        assert out == data


def test_losing_both_copies_of_a_block_names_it(sample):
    _data, blob, _summary = sample
    first, second, slot = slot_offsets(blob)
    damaged = bytearray(blob)
    for copies in (first, second):
        damaged[copies[7] : copies[7] + slot] = bytes(slot)
    report = verify(bytes(damaged))
    assert not report.ok and report.failed_blocks == [7]
    assert "UNRECOVERABLE" in report.summary()
    with pytest.raises(CorruptionError, match="Block 7") as caught:
        read(bytes(damaged))
    assert caught.value.report.failed_blocks == [7]


def test_swapped_blocks_are_detected_not_reordered(sample):
    data, blob, _summary = sample
    first, second, slot = slot_offsets(blob)
    swapped = bytearray(blob)
    for copies in (first, second):
        a = bytes(blob[copies[2] : copies[2] + slot])
        b = bytes(blob[copies[3] : copies[3] + slot])
        swapped[copies[2] : copies[2] + slot] = b
        swapped[copies[3] : copies[3] + slot] = a
    with pytest.raises(CorruptionError):
        read(bytes(swapped))
    assert sorted(verify(bytes(swapped)).failed_blocks) == [2, 3]

    one_copy = bytearray(blob)
    one_copy[first[2] : first[2] + slot] = blob[first[3] : first[3] + slot]
    assert read(bytes(one_copy))[0] == data


def test_a_block_from_another_backup_is_refused(sample):
    _data, blob, _summary = sample
    other, _ = write(os.urandom(40_000), **SMALL)
    first, second, slot = slot_offsets(blob)
    mixed = bytearray(blob)
    for copies in (first, second):
        mixed[copies[4] : copies[4] + slot] = other[copies[4] : copies[4] + slot]
    assert verify(bytes(mixed)).failed_blocks == [4]


def test_the_tags_of_both_copies_damaged_is_still_read(sample):
    data, blob, _summary = sample
    first, second, slot = slot_offsets(blob)
    damaged = bytearray(blob)
    damaged[first[6] + slot - 1] ^= 1
    damaged[second[6] + slot - 2] ^= 1
    out, _reader = read(bytes(damaged))
    assert out == data
    report = verify(bytes(damaged))
    assert report.ok and not report.unverified_blocks


def test_garbage_appended_after_the_container_is_tolerated(sample):
    data, blob, _summary = sample
    out, reader = read(blob + os.urandom(5000))
    assert out == data
    assert "back header" in reader.report.metadata_damaged


def resealed(blob, **changes):
    opened = open_sealed_header(blob[:HEADER_SIZE])
    fields = list(HEADER_BODY.unpack(opened[1]))
    names = [
        "flags", "nsym", "block_size", "interleave", "time_cost", "memory_cost",
        "parallelism", "reserved", "salt", "container_id", "nonce_prefix",
        "wrap_nonce", "wrapped_key",
    ]
    for name, value in changes.items():
        fields[names.index(name)] = value
    header = seal_header(2, HEADER_BODY.pack(*fields))
    return header + blob[HEADER_SIZE:-HEADER_SIZE] + header


@pytest.mark.parametrize(
    "changes",
    [
        {"time_cost": 1000},
        {"memory_cost": 4 * 1024 * 1024},
        {"parallelism": 0},
        {"memory_cost": 4},
        {"block_size": 0},
        {"block_size": 1 << 30},
        {"nsym": 0},
        {"nsym": 200},
        {"interleave": 0},
        {"interleave": 5000},
        {"reserved": 1},
    ],
)
def test_hostile_header_values_are_refused_before_any_work(sample, changes):
    _data, blob, _summary = sample
    with pytest.raises(ContainerError):
        StreamReader(io.BytesIO(resealed(blob, **changes)), PASS)


def test_a_resealed_header_with_other_parameters_cannot_decrypt(sample):
    _data, blob, _summary = sample
    with pytest.raises(InvalidPassphrase):
        StreamReader(io.BytesIO(resealed(blob, time_cost=2)), PASS)
    with pytest.raises(InvalidPassphrase):
        StreamReader(io.BytesIO(resealed(blob, salt=os.urandom(16))), PASS)


def test_every_header_field_is_bound_to_the_data_key(sample):
    _data, blob, _summary = sample
    for changes in ({"flags": 7}, {"nonce_prefix": os.urandom(7)}, {"interleave": 5}):
        with pytest.raises(InvalidPassphrase):
            StreamReader(io.BytesIO(resealed(blob, **changes)), PASS)
        assert StreamReader(io.BytesIO(resealed(blob, **changes))).header is not None


def test_the_writer_refuses_parameters_its_reader_would_refuse():
    for options in (
        {"block_size": 100},
        {"nsym": 1},
        {"interleave": 0},
        {"interleave": 4096, "block_size": 1 << 20},
        {"workers": 0},
        {"flags": 1 << 16},
    ):
        with pytest.raises(ValueError):
            StreamWriter(io.BytesIO(), PASS, kdf_params=FAST, **options)
    with pytest.raises(CryptoError):
        StreamWriter(io.BytesIO(), PASS, kdf_params=KDFParams(time_cost=11))


def test_a_closed_writer_refuses_more_data_and_close_is_idempotent():
    sink = io.BytesIO()
    writer = StreamWriter(sink, PASS, kdf_params=FAST, **SMALL)
    writer.write(b"data")
    summary = writer.close()
    assert writer.close() is summary
    with pytest.raises(ValueError):
        writer.write(b"more")


def test_an_aborted_writer_leaves_an_unreadable_file():
    sink = io.BytesIO()
    with pytest.raises(RuntimeError):
        with StreamWriter(sink, PASS, kdf_params=FAST, **SMALL) as writer:
            writer.write(os.urandom(10_000))
            raise RuntimeError("source failed")
    with pytest.raises(ContainerError):
        read(sink.getvalue())


def test_sources_must_be_seekable_binary_files(tmp_path):
    class Unseekable:
        def read(self, size=-1):
            return b""

    with pytest.raises(ContainerError):
        StreamReader(Unseekable())
    with pytest.raises(ContainerError):
        StreamReader(str(tmp_path / "x.dbs"))


def test_files_on_disk_round_trip(tmp_path):
    data = os.urandom(200_000)
    path = tmp_path / "backup.dbs"
    with open(path, "wb") as sink:
        summary = StreamWriter(sink, PASS, kdf_params=FAST, **SMALL)
        summary.write(data)
        summary.close()
    with open(path, "rb") as source:
        assert StreamReader(source, PASS).read_all() == data


def test_descriptor_positions_follow_the_schedule():
    layout = list(schedule(10, 4))
    first = {index: position for position, index, is_first in layout if is_first}
    second = {index: position for position, index, is_first in layout if not is_first}
    assert [first_copy_position(index, 4) for index in range(10)] == [first[i] for i in range(10)]
    assert all(second[i] - first[i] >= 5 for i in range(10))
    assert sorted(position for position, _i, _f in layout) == list(range(20))
    assert DESCRIPTOR.size == 16


MUTATIONS = ("flip", "zero", "truncate", "insert", "duplicate", "reseal")


def mutate(blob, rng):
    kind = rng.choice(MUTATIONS)
    data = bytearray(blob)
    if kind == "flip":
        for _ in range(rng.randint(1, 60)):
            data[rng.randrange(len(data))] ^= 1 << rng.randrange(8)
    elif kind == "zero":
        start = rng.randrange(len(data))
        data[start : start + rng.randint(1, 3000)] = b""
        data[start:start] = bytes(min(3000, len(blob) - start))
    elif kind == "truncate":
        del data[rng.randrange(len(data)) :]
    elif kind == "insert":
        start = rng.randrange(len(data))
        data[start:start] = os.urandom(rng.randint(1, 500))
    elif kind == "duplicate":
        start = rng.randrange(len(data))
        data[start:start] = data[start : start + rng.randint(1, 3000)]
    else:
        body = bytearray(os.urandom(HEADER_BODY.size))
        struct.pack_into(">HHI", body, 0, 0, rng.choice([2, 16, 300]), rng.choice([512, 1024, 0]))
        header = seal_header(2, bytes(body))
        data[:HEADER_SIZE] = header
        if rng.random() < 0.5:
            data[-HEADER_SIZE:] = header
    return bytes(data)


def test_fuzzed_containers_only_raise_container_errors():
    data = os.urandom(12_000)
    blob, _summary = write(data, **SMALL)
    rng = random.Random(5)
    for iteration in range(250):
        candidate = mutate(blob, rng)
        try:
            report = StreamReader(io.BytesIO(candidate)).verify()
        except ContainerError:
            pass
        else:
            assert isinstance(report.summary(), str)
        if iteration % 2:
            continue
        try:
            out = StreamReader(io.BytesIO(candidate), PASS).read_all()
        except ContainerError:
            continue
        except InvalidPassphrase:
            assert candidate[:HEADER_SIZE] != blob[:HEADER_SIZE]
            continue
        assert out == data


def test_header_parsing_rejects_every_wrong_size():
    for size in (0, HEADER_BODY.size - 1, HEADER_BODY.size + 1):
        with pytest.raises(ContainerError):
            StreamHeader.parse(bytes(size))


def peak_bytes(action):
    tracemalloc.start()
    try:
        action()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


class CountingSink:
    def __init__(self):
        self.size = 0

    def write(self, data):
        self.size += len(data)


def stream_of(size, piece=1 << 20):
    block = os.urandom(piece)
    for start in range(0, size, piece):
        yield block[: min(piece, size - start)]


@pytest.mark.parametrize(
    "size",
    [
        24 * 1024 * 1024,
        pytest.param(
            200 * 1024 * 1024,
            marks=pytest.mark.skipif(
                not os.environ.get("DBS_SLOW_TESTS"), reason="set DBS_SLOW_TESTS=1"
            ),
        ),
    ],
)
def test_writer_and_reader_memory_stays_bounded(tmp_path, size):
    path = tmp_path / "big.dbs"

    def write_large():
        with open(path, "wb") as sink:
            writer = StreamWriter(sink, PASS, kdf_params=FAST, workers=1)
            for piece in stream_of(size):
                writer.write(piece)
            writer.close()

    def read_large():
        with open(path, "rb") as source:
            total = sum(len(chunk) for chunk in StreamReader(source, PASS))
        assert total == size

    budget = 24 * 1024 * 1024
    assert peak_bytes(write_large) < budget
    assert peak_bytes(read_large) < budget


def test_a_header_dataclass_round_trips_its_canonical_bytes(sample):
    _data, blob, _summary = sample
    header = StreamReader(io.BytesIO(blob)).header
    assert header.seal() == blob[:HEADER_SIZE]
    assert dataclasses.replace(header, flags=1).seal() != blob[:HEADER_SIZE]
