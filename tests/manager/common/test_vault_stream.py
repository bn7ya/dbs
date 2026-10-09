from __future__ import annotations

import hashlib
import io
import os
import secrets

import pytest
from django.test import override_settings

from dbs.manager import vault
from dbs.manager.vault import (
    BASE_NONCE_BYTES,
    CHUNK_SIZE_BYTES,
    KEY_ID_BYTES,
    NONCE_BYTES,
    STREAM_HEADER_BYTES,
    TAG_BYTES,
    VaultError,
    open_stream,
    seal,
    seal_stream,
    unseal,
)

CHUNK = 64
CONTEXT = "backups.file"

MAGIC_AT = 0
VERSION_AT = 8
KEY_ID_AT = VERSION_AT + 1
CHUNK_SIZE_AT = KEY_ID_AT + KEY_ID_BYTES
BASE_NONCE_AT = CHUNK_SIZE_AT + CHUNK_SIZE_BYTES
KEY_NONCE_AT = BASE_NONCE_AT + BASE_NONCE_BYTES
WRAPPED_KEY_AT = KEY_NONCE_AT + NONCE_BYTES


@pytest.fixture(autouse=True)
def small_chunks(monkeypatch):
    monkeypatch.setattr(vault, "CHUNK_BYTES", CHUNK)


def new_key() -> str:
    return secrets.token_urlsafe(32)


def using(*keys):
    return override_settings(
        SECRET_KEY=keys[0] if keys else "", SECRET_KEY_FALLBACKS=list(keys[1:])
    )


def sealed(plaintext: bytes, context: str = CONTEXT) -> bytes:
    target = io.BytesIO()
    seal_stream(io.BytesIO(plaintext), target, context=context)
    return target.getvalue()


def opened(data: bytes, context: str = CONTEXT) -> bytes:
    return b"".join(open_stream(io.BytesIO(data), context=context))


def records(data: bytes) -> list[bytes]:
    body = data[STREAM_HEADER_BYTES:]
    size = CHUNK + TAG_BYTES
    return [body[at : at + size] for at in range(0, len(body), size)]


def joined(data: bytes, parts: list[bytes]) -> bytes:
    return data[:STREAM_HEADER_BYTES] + b"".join(parts)


def flipped(data: bytes, position: int) -> bytes:
    altered = bytearray(data)
    altered[position] ^= 0x01
    return bytes(altered)


class Trickle:
    def __init__(self, data: bytes) -> None:
        self.data = io.BytesIO(data)

    def read(self, size: int = -1) -> bytes:
        return self.data.read(min(size, 7))


@pytest.mark.parametrize(
    "size",
    [0, 1, CHUNK - 1, CHUNK, CHUNK + 1, 3 * CHUNK],
    ids=[
        "empty",
        "one byte",
        "a byte short",
        "one chunk",
        "a byte over",
        "three chunks",
    ],
)
def test_a_sealed_stream_opens_to_what_was_sealed(size):
    plaintext = os.urandom(size)
    target = io.BytesIO()

    result = seal_stream(io.BytesIO(plaintext), target, context=CONTEXT)

    data = target.getvalue()
    assert (result.size, result.sha256) == (size, hashlib.sha256(plaintext).hexdigest())
    assert len(data) == STREAM_HEADER_BYTES + len(records(data)) * TAG_BYTES + size
    assert len(records(data)) == max(1, -(-size // CHUNK))
    assert opened(data) == plaintext
    if size >= 8:
        assert plaintext[:8] not in data


def test_the_default_chunk_size_round_trips(monkeypatch):
    monkeypatch.undo()
    plaintext = os.urandom(2 * vault.CHUNK_BYTES + 12345)

    data = sealed(plaintext)

    assert len(data) == STREAM_HEADER_BYTES + 3 * TAG_BYTES + len(plaintext)
    assert opened(data) == plaintext


def test_a_source_and_a_file_that_read_a_few_bytes_at_a_time_still_round_trip():
    plaintext = os.urandom(2 * CHUNK + 5)
    target = io.BytesIO()

    seal_stream(Trickle(plaintext), target, context=CONTEXT)

    assert (
        b"".join(open_stream(Trickle(target.getvalue()), context=CONTEXT)) == plaintext
    )


def test_an_empty_file_yields_no_chunk():
    assert list(open_stream(io.BytesIO(sealed(b"")), context=CONTEXT)) == []


def test_the_same_file_seals_differently_each_time():
    plaintext = os.urandom(CHUNK)

    assert sealed(plaintext) != sealed(plaintext)


@pytest.mark.parametrize(
    "position",
    [
        MAGIC_AT,
        VERSION_AT,
        KEY_ID_AT,
        CHUNK_SIZE_AT + CHUNK_SIZE_BYTES - 1,
        BASE_NONCE_AT,
        KEY_NONCE_AT,
        WRAPPED_KEY_AT,
        STREAM_HEADER_BYTES - 1,
    ],
    ids=[
        "magic",
        "version",
        "key id",
        "chunk size",
        "base nonce",
        "key nonce",
        "wrapped key",
        "wrapped key tag",
    ],
)
def test_a_changed_header_byte_does_not_open(position):
    data = sealed(os.urandom(2 * CHUNK))

    with pytest.raises(VaultError):
        opened(flipped(data, position))


@pytest.mark.parametrize(
    "position",
    [
        STREAM_HEADER_BYTES,
        STREAM_HEADER_BYTES + CHUNK - 1,
        STREAM_HEADER_BYTES + CHUNK + TAG_BYTES - 1,
        STREAM_HEADER_BYTES + CHUNK + TAG_BYTES,
        -TAG_BYTES - 1,
        -1,
    ],
    ids=[
        "first chunk",
        "end of first chunk",
        "first tag",
        "second chunk",
        "last chunk",
        "last tag",
    ],
)
def test_a_changed_byte_in_a_record_does_not_open(position):
    data = sealed(os.urandom(2 * CHUNK + 10))

    with pytest.raises(VaultError):
        opened(flipped(data, position))


def test_the_chunks_before_a_changed_record_are_yielded_and_the_rest_are_not():
    plaintext = os.urandom(3 * CHUNK)
    data = flipped(sealed(plaintext), STREAM_HEADER_BYTES + 2 * (CHUNK + TAG_BYTES))
    received = []

    with pytest.raises(VaultError):
        for chunk in open_stream(io.BytesIO(data), context=CONTEXT):
            received.append(chunk)

    assert received == [plaintext[:CHUNK], plaintext[CHUNK : 2 * CHUNK]]


@pytest.mark.parametrize(
    "size", [2 * CHUNK + 10, 3 * CHUNK], ids=["short last", "full last"]
)
def test_a_file_without_its_last_record_does_not_open(size):
    data = sealed(os.urandom(size))

    with pytest.raises(VaultError):
        opened(joined(data, records(data)[:-1]))


@pytest.mark.parametrize("cut", [1, TAG_BYTES - 1, TAG_BYTES, TAG_BYTES + 1, CHUNK])
def test_a_file_cut_inside_a_record_does_not_open(cut):
    data = sealed(os.urandom(3 * CHUNK))

    with pytest.raises(VaultError):
        opened(data[:-cut])


def test_a_header_with_no_record_does_not_open():
    data = sealed(b"")

    with pytest.raises(VaultError, match="cut short"):
        opened(data[:STREAM_HEADER_BYTES])


@pytest.mark.parametrize(
    "size", [CHUNK + 10, 2 * CHUNK], ids=["short last", "full last"]
)
@pytest.mark.parametrize(
    "extra", [b"\x00", os.urandom(TAG_BYTES), os.urandom(CHUNK + TAG_BYTES)]
)
def test_anything_after_the_last_record_does_not_open(size, extra):
    data = sealed(os.urandom(size))

    with pytest.raises(VaultError):
        opened(data + extra)


def test_records_in_another_order_do_not_open():
    data = sealed(os.urandom(3 * CHUNK))
    first, second, third = records(data)

    with pytest.raises(VaultError):
        opened(joined(data, [second, first, third]))


def test_a_record_from_another_file_does_not_open():
    data, other = sealed(os.urandom(2 * CHUNK)), sealed(os.urandom(2 * CHUNK))

    with pytest.raises(VaultError):
        opened(joined(data, [records(other)[0], records(data)[1]]))


def test_a_header_from_another_file_does_not_open():
    data, other = sealed(os.urandom(2 * CHUNK)), sealed(os.urandom(2 * CHUNK))

    with pytest.raises(VaultError):
        opened(joined(other, records(data)))


def test_a_stream_does_not_open_for_another_use():
    data = sealed(b"server files")

    with pytest.raises(VaultError, match="another use"):
        open_stream(io.BytesIO(data), context="servers.password")


def test_a_stream_and_a_sealed_value_are_never_mistaken_for_each_other():
    with pytest.raises(VaultError):
        unseal(sealed(b"server files"), context=CONTEXT)
    with pytest.raises(VaultError):
        open_stream(io.BytesIO(seal(b"x" * 200, context=CONTEXT)), context=CONTEXT)


def test_rotation_keeps_old_streams_open_and_seals_new_ones_with_the_new_key():
    old, new = new_key(), new_key()
    with using(old):
        before = sealed(b"kept")

    with using(new, old):
        assert opened(before) == b"kept"
        after = sealed(b"fresh")

    key_ids = slice(KEY_ID_AT, KEY_ID_AT + KEY_ID_BYTES)
    assert after[key_ids] != before[key_ids]
    with using(new):
        assert opened(after) == b"fresh"


def test_a_stream_sealed_with_a_key_no_longer_listed_does_not_open():
    with using(new_key()):
        data = sealed(b"orphaned")

    with (
        using(new_key()),
        pytest.raises(VaultError, match="no longer"),
    ):
        open_stream(io.BytesIO(data), context=CONTEXT)


@pytest.mark.parametrize(
    "data",
    [b"", b"DBSISEAL", os.urandom(STREAM_HEADER_BYTES + TAG_BYTES), b"\x01" * 200],
    ids=["empty", "magic only", "noise", "a sealed value's version byte"],
)
def test_something_the_vault_did_not_seal_is_refused_before_any_chunk(data):
    with pytest.raises(VaultError, match="not sealed by the vault"):
        open_stream(io.BytesIO(data), context=CONTEXT)


def test_a_chunk_size_beyond_the_limit_is_refused(monkeypatch):
    monkeypatch.setattr(vault, "CHUNK_BYTES", vault.MAX_CHUNK_BYTES + 1)
    data = sealed(b"small")

    with pytest.raises(VaultError, match="impossible chunk size"):
        open_stream(io.BytesIO(data), context=CONTEXT)


def test_a_file_of_more_chunks_than_the_counter_counts_is_refused():
    with pytest.raises(VaultError, match="too large"):
        vault._chunk_nonce(bytes(BASE_NONCE_BYTES), 2**32, last=False)
