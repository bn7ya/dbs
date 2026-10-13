"""Vectorised Reed-Solomon: byte-identical to reedsolo, and a v1 read path that only decodes damage."""

import random

import pytest
from reedsolo import RSCodec

from dbs.container import encode_copy, repair_copies, rs
from dbs.container.blocks import _decode_block, _decode_with_reedsolo, _hash

SIZES = [0, 1, 2, 100, 238, 239, 240, 478, 479, 1000, 4096, 65535, 65536, 65537]


def random_bytes(rng, size):
    return rng.randbytes(size)


@pytest.mark.parametrize("nsym", [1, 2, 7, 16, 32, 64, 128, 200, 254])
def test_parity_is_byte_identical_to_reedsolo(nsym):
    rng = random.Random(nsym)
    codec = RSCodec(nsym)
    message_len = 255 - nsym
    sizes = SIZES + [message_len - 1, message_len, message_len + 1, 3 * message_len + 1]
    if nsym >= 64:
        sizes = [size for size in sizes if size <= 4096]
    for size in sizes:
        data = random_bytes(rng, size)
        expected = bytes(codec.encode(data))
        assert rs.encode(data, nsym) == expected
        assert rs.encoded_length(size, nsym) == len(expected)


def test_many_blocks_encode_in_one_batch():
    rng = random.Random(7)
    codec = RSCodec(16)
    blocks = [random_bytes(rng, rng.randint(0, 5000)) for _ in range(25)]
    assert rs.encode_many(blocks, 16) == [bytes(codec.encode(block)) for block in blocks]


def test_large_inputs_cross_the_parity_batch_boundary(monkeypatch):
    monkeypatch.setattr(rs, "PARITY_BATCH_ROWS", 4)
    rng = random.Random(8)
    data = random_bytes(rng, 239 * 13 + 11)
    assert rs.encode(data, 16) == bytes(RSCodec(16).encode(data))


def test_an_intact_codeword_strips_without_decoding():
    rng = random.Random(9)
    data = random_bytes(rng, 70_000)
    encoded = rs.encode(data, 16)
    assert rs.strip_parity(encoded, 16) == data
    assert rs.damaged_codewords(encoded, 16) == []
    assert rs.decode(encoded, 16) == data


def test_damaged_codewords_are_located():
    rng = random.Random(10)
    data = random_bytes(rng, 10_000)
    encoded = bytearray(rs.encode(data, 16))
    encoded[3] ^= 1
    encoded[255 * 5 + 250] ^= 0x80
    encoded[-1] ^= 0x10
    last = rs.codeword_count(len(encoded)) - 1
    assert rs.damaged_codewords(bytes(encoded), 16) == [0, 5, last]
    assert rs.decode(bytes(encoded), 16) == data


def test_decode_matches_reedsolo_on_both_sides_of_the_budget():
    rng = random.Random(11)
    codec = RSCodec(16)
    data = random_bytes(rng, 5_000)
    encoded = rs.encode(data, 16)
    for errors in (1, 4, 8, 9, 12, 30):
        damaged = bytearray(encoded)
        for position in rng.sample(range(255), errors):
            damaged[255 * 2 + position] ^= rng.randint(1, 255)
        try:
            expected = bytes(codec.decode(bytes(damaged))[0])
        except Exception:
            expected = None
        assert rs.decode(bytes(damaged), 16) == expected


def test_malformed_lengths_fall_back_to_reedsolo():
    assert not rs.is_well_formed(255 + 16, 16)
    assert rs.strip_parity(b"\x00" * (255 + 10), 16) is None
    assert rs.damaged_codewords(b"\x00" * (255 + 10), 16) is None


@pytest.mark.parametrize("nsym", [0, 255, -1, "16"])
def test_unsupported_nsym_is_refused(nsym):
    with pytest.raises(ValueError):
        rs.check_nsym(nsym)


def test_encode_copy_is_byte_identical_to_the_reedsolo_layout():
    rng = random.Random(12)
    data = random_bytes(rng, 300_000)
    encoded, plan = encode_copy(data, block_size=65_536, nsym=16)
    codec = RSCodec(16)
    expected = b"".join(
        bytes(codec.encode(data[offset : offset + 65_536]))
        for offset in range(0, len(data), 65_536)
    )
    assert encoded == expected
    assert plan.n_blocks == 5


def test_v1_block_decoding_agrees_with_reedsolo_under_random_damage():
    rng = random.Random(13)
    nsym = 16
    rsc = RSCodec(nsym)
    for trial in range(60):
        block = random_bytes(rng, rng.choice([1, 239, 1_000, 4_096, 10_000]))
        encoded = rs.encode(block, nsym)
        data_hash = _hash(block)
        damaged = bytearray(encoded)
        codewords = rs.codeword_count(len(encoded))
        for _ in range(rng.choice([0, 1, 3, 8, 9, 20, 60])):
            index = rng.randrange(codewords)
            start = index * 255
            end = min(start + 255, len(encoded))
            damaged[rng.randrange(start, end)] ^= rng.randint(1, 255)
        damaged = bytes(damaged)

        fast = _decode_block(rsc, damaged, data_hash)
        legacy = _decode_with_reedsolo(rsc, damaged, data_hash)
        if legacy is not None:
            assert fast == legacy == block
        elif fast is not None:
            assert fast == block
            assert rs.strip_parity(damaged, nsym) == block


def test_parity_only_damage_beyond_the_budget_is_still_read():
    rng = random.Random(14)
    rsc = RSCodec(16)
    block = random_bytes(rng, 1_000)
    damaged = bytearray(rs.encode(block, 16))
    for offset in range(239, 255):
        damaged[offset] ^= 0xFF
    assert _decode_with_reedsolo(rsc, bytes(damaged), _hash(block)) is None
    assert _decode_block(rsc, bytes(damaged), _hash(block)) == block


def test_v1_clean_copies_are_read_without_decoding(monkeypatch):
    rng = random.Random(15)
    data = random_bytes(rng, 200_000)
    encoded, plan = encode_copy(data)

    def refuse(*args, **kwargs):
        raise AssertionError("an intact block must not reach the decoder")

    monkeypatch.setattr(RSCodec, "decode", refuse)
    recovered, report = repair_copies(encoded, encoded, plan)
    assert recovered == data
    assert report.blocks_direct == plan.n_blocks and not report.healed


def test_v1_repair_still_heals_through_the_fast_path():
    rng = random.Random(16)
    data = random_bytes(rng, 200_000)
    encoded, plan = encode_copy(data)
    damaged = bytearray(encoded)
    for block_index, offset in enumerate(range(0, len(encoded), plan.enc_lens[0])):
        damaged[offset + 17] ^= 0x41
        damaged[offset + 600] ^= 0x13
    recovered, report = repair_copies(bytes(damaged), None, plan)
    assert recovered == data
    assert report.blocks_rs_corrected == plan.n_blocks
    assert report.copies_available == 1


def test_codewords_damaged_in_different_copies_are_rebuilt_from_both():
    rng = random.Random(17)
    data = random_bytes(rng, 5_000)
    encoded = rs.encode(data, 16)
    first, second = bytearray(encoded), bytearray(encoded)
    first[10:40] = b"\xff" * 30
    second[600:630] = b"\xaa" * 30
    repaired, used, decoded = rs.repair_from_copies([bytes(first), bytes(second)], 16)
    assert repaired == data and used == {0, 1} and not decoded


def test_the_same_codeword_damaged_in_both_copies_uses_erasures():
    rng = random.Random(18)
    data = random_bytes(rng, 2_000)
    encoded = rs.encode(data, 16)
    first, second = bytearray(encoded), bytearray(encoded)
    for offset in range(300, 312):
        first[offset] = encoded[offset] ^ 0x0F
        second[offset] = encoded[offset] ^ 0xF0
    repaired, _used, decoded = rs.repair_from_copies([bytes(first), bytes(second)], 16)
    assert repaired == data and decoded


def test_codewords_lost_in_both_copies_cannot_be_rebuilt():
    rng = random.Random(19)
    encoded = rs.encode(random_bytes(rng, 2_000), 16)
    first, second = bytearray(encoded), bytearray(encoded)
    first[0:40] = bytes(40)
    second[0:40] = b"\x01" * 40
    assert rs.repair_from_copies([bytes(first), bytes(second)], 16)[0] is None
    assert rs.repair_from_copies([], 16)[0] is None
    assert rs.repair_from_copies([encoded, encoded[:-1]], 16)[0] is None
