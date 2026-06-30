"""Container layer: framing, dual-copy self-healing, Reed-Solomon, redundancy."""

import os

from dbs.container import encode_copy, repair_copies, write_container, read_container
from dbs.container.blocks import DEFAULT_BLOCK_SIZE
from dbs.container.format import (
    FLAG_ENCRYPTED,
    FLAG_FEC,
    HEADER_SIZE,
    copy_offsets,
)


def _manifest(plan):
    return {
        "format": "DBS",
        "version": 1,
        "compression": None,
        "copy_len": plan.copy_len,
        "blocks": plan.to_dict(),
        "crypto": {},
        "payload_sha256": "x",
    }


def test_clean_roundtrip():
    data = os.urandom(200_000)
    enc, plan = encode_copy(data, block_size=DEFAULT_BLOCK_SIZE)
    recovered, report = repair_copies(enc, enc, plan)
    assert recovered == data
    assert report.ok and not report.healed


def test_whole_block_wiped_in_copy_a_restored_from_b():
    data = os.urandom(200_000)
    enc, plan = encode_copy(data)
    damaged = bytearray(enc)
    damaged[: plan.enc_lens[0]] = b"\x00" * plan.enc_lens[0]  # destroy block 0 of A
    recovered, report = repair_copies(bytes(damaged), enc, plan)
    assert recovered == data
    assert report.healed and report.blocks_used_b >= 1


def test_bit_rot_in_both_copies_corrected_by_reed_solomon():
    data = os.urandom(200_000)
    enc, plan = encode_copy(data)
    a, b = bytearray(enc), bytearray(enc)
    for i in (3, 90, 222, 333, 410, 590):  # 6 byte errors, within nsym=16 budget
        a[i] ^= 0xFF
        b[i] ^= 0xFF
    recovered, report = repair_copies(bytes(a), bytes(b), plan)
    assert recovered == data
    assert report.healed and report.blocks_rs_corrected >= 1


def test_damage_beyond_capacity_is_unrecoverable():
    data = os.urandom(200_000)
    enc, plan = encode_copy(data)
    a, b = bytearray(enc), bytearray(enc)
    a[0:400] = b"\x01" * 400  # far more than RS can fix in one codeword
    b[0:400] = b"\x02" * 400
    recovered, report = repair_copies(bytes(a), bytes(b), plan)
    assert recovered is None
    assert not report.ok and 0 in report.failed_blocks


def test_head_header_corruption_falls_back_to_tail():
    data = os.urandom(50_000)
    enc, plan = encode_copy(data)
    blob = bytearray(write_container(_manifest(plan), enc, enc, flags=FLAG_ENCRYPTED | FLAG_FEC))
    blob[0:8] = b"XXXXXXXX"  # smash the head magic
    manifest, a, b = read_container(bytes(blob))
    assert a == enc and b == enc


def test_corrupt_first_manifest_falls_back_to_duplicate():
    data = os.urandom(50_000)
    enc, plan = encode_copy(data)
    blob = bytearray(write_container(_manifest(plan), enc, enc, flags=FLAG_ENCRYPTED | FLAG_FEC))
    blob[HEADER_SIZE + 2] ^= 0xFF  # corrupt a byte of the first manifest copy
    manifest, a, b = read_container(bytes(blob))
    assert manifest["copy_len"] == plan.copy_len


def test_copy_offsets_addresses_the_right_bytes():
    data = os.urandom(50_000)
    enc, plan = encode_copy(data)
    blob = write_container(_manifest(plan), enc, enc, flags=FLAG_ENCRYPTED | FLAG_FEC)
    a_off, b_off, copy_len = copy_offsets(blob)
    assert blob[a_off : a_off + copy_len] == enc
    assert blob[b_off : b_off + copy_len] == enc
