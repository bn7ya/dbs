"""Header copies: any single damaged byte is survivable, and only a verified header names a version."""

import io
import os
import struct

import pytest

from dbs.container import read_container
from tests.format1 import encode_copy, write_container
from dbs.container.format import (
    FLAG_ENCRYPTED,
    FLAG_FEC,
    FORMAT_VERSION,
    HEADER_SIZE,
    MAGIC,
    container_version,
    copy_offsets,
    open_sealed_header,
    read_format_version,
    seal_header,
)
from dbs.exceptions import ContainerError


def _manifest(plan, **overrides):
    manifest = {
        "format": "DBS",
        "version": 1,
        "compression": None,
        "copy_len": plan.copy_len,
        "blocks": plan.to_dict(),
        "crypto": {},
        "payload_sha256": "x",
    }
    manifest.update(overrides)
    return manifest


@pytest.fixture(scope="module")
def v1_blob():
    data = os.urandom(20_000)
    encoded, plan = encode_copy(data, block_size=4096)
    blob = write_container(_manifest(plan), encoded, encoded, flags=FLAG_ENCRYPTED | FLAG_FEC)
    return blob, encoded


@pytest.mark.parametrize("pattern", [0x01, 0x80, 0xFF])
def test_every_byte_of_the_front_header_is_survivable(v1_blob, pattern):
    blob, encoded = v1_blob
    for offset in range(HEADER_SIZE):
        damaged = bytearray(blob)
        damaged[offset] ^= pattern
        manifest, copy_a, copy_b = read_container(bytes(damaged))
        assert copy_a == encoded and copy_b == encoded, offset
        assert container_version(bytes(damaged)) == FORMAT_VERSION, offset


def test_every_byte_of_the_back_header_is_survivable(v1_blob):
    blob, encoded = v1_blob
    for offset in range(len(blob) - HEADER_SIZE, len(blob)):
        damaged = bytearray(blob)
        damaged[offset] ^= 0xFF
        _manifest_read, copy_a, _copy_b = read_container(bytes(damaged))
        assert copy_a == encoded
        assert container_version(bytes(damaged)) == FORMAT_VERSION


def test_a_flipped_version_bit_never_reads_as_a_future_format(v1_blob):
    blob, _encoded = v1_blob
    for bit in range(16):
        front = bytearray(blob)
        struct.pack_into(">H", front, 8, FORMAT_VERSION ^ (1 << bit))
        assert container_version(bytes(front)) == FORMAT_VERSION

        both = bytearray(front)
        struct.pack_into(">H", both, len(both) - HEADER_SIZE + 8, FORMAT_VERSION ^ (1 << bit))
        assert container_version(bytes(both)) is None
        with pytest.raises(ContainerError):
            read_container(bytes(both))


def test_a_damaged_front_header_and_first_manifest_still_read(v1_blob):
    blob, encoded = v1_blob
    damaged = bytearray(blob)
    damaged[20] ^= 0x55
    damaged[HEADER_SIZE + 5] ^= 0x55
    _manifest_read, copy_a, _copy_b = read_container(bytes(damaged))
    assert copy_a == encoded


def test_a_moved_manifest_offset_is_not_trusted(v1_blob):
    blob, encoded = v1_blob
    damaged = bytearray(blob)
    struct.pack_into(">Q", damaged, 16, HEADER_SIZE + 4096)
    a_off, b_off, copy_len = copy_offsets(bytes(damaged))
    assert damaged[a_off : a_off + copy_len] == encoded


def test_both_manifests_lost_is_reported_as_such(v1_blob):
    blob, _encoded = v1_blob
    damaged = bytearray(blob)
    manifest_len = struct.unpack_from(">Q", damaged, 24)[0]
    damaged[HEADER_SIZE + 1] ^= 1
    damaged[HEADER_SIZE + manifest_len + 1] ^= 1
    with pytest.raises(ContainerError, match="Both manifest copies"):
        read_container(bytes(damaged))


def test_garbage_is_not_a_container():
    with pytest.raises(ContainerError, match="Not a DBS container"):
        read_container(os.urandom(5000))
    assert container_version(b"") is None
    assert container_version(MAGIC) is None


def test_a_hash_valid_but_malformed_manifest_raises_container_error():
    encoded, plan = encode_copy(b"x" * 100)
    for bad in ("many", None, -5, [1]):
        blob = write_container(
            _manifest(plan, copy_len=bad), encoded, encoded, flags=FLAG_ENCRYPTED
        )
        with pytest.raises(ContainerError):
            read_container(blob)


def test_sealed_headers_detect_every_single_bit_flip():
    sealed = seal_header(7, b"future body bytes")
    assert open_sealed_header(sealed) == (7, b"future body bytes")
    for offset in range(len(sealed)):
        for bit in range(8):
            damaged = bytearray(sealed)
            damaged[offset] ^= 1 << bit
            assert open_sealed_header(bytes(damaged)) is None


def test_sealed_headers_refuse_version_one_and_oversize_bodies():
    with pytest.raises(ValueError):
        seal_header(1, b"")
    with pytest.raises(ValueError):
        seal_header(3, b"x" * 5000)


def test_a_verified_future_version_is_reported_not_called_garbage(v1_blob):
    blob, _encoded = v1_blob
    future = seal_header(9, b"") + blob
    assert container_version(future) == 9
    with pytest.raises(ContainerError, match="Unsupported container format version 9"):
        read_container(future)


def test_a_version_two_container_points_to_the_stream_reader():
    sealed = seal_header(2, b"\x00" * 40)
    with pytest.raises(ContainerError, match="StreamReader"):
        read_container(sealed + os.urandom(1000) + sealed)


def test_the_trailing_sealed_copy_is_found_when_the_front_is_damaged():
    sealed = seal_header(5, b"tail")
    blob = bytearray(sealed + os.urandom(3000) + sealed)
    blob[3] ^= 0xFF
    assert container_version(bytes(blob)) == 5


def test_read_format_version_reads_files_and_restores_their_position(v1_blob):
    blob, _encoded = v1_blob
    handle = io.BytesIO(b"prefix" + blob)
    handle.seek(6)
    assert read_format_version(handle) == FORMAT_VERSION
    assert handle.tell() == 6
    assert read_format_version(io.BytesIO(b"nothing here")) is None


def test_read_format_version_refuses_paths_and_text_files(tmp_path):
    with pytest.raises(ContainerError):
        read_format_version(str(tmp_path / "x.dbs"))
    with pytest.raises(ContainerError):
        read_format_version(io.StringIO("DBSCON01" + "x" * 200))
