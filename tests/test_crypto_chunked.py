"""Chunked AEAD: each chunk is bound to its position, its finality and the header."""

import os

import pytest

from dbs.crypto.chunked import (
    NONCE_PREFIX_LENGTH,
    ChunkCipher,
    chunk_nonce,
    new_nonce_prefix,
    unwrap_key,
    wrap_key,
)
from dbs.crypto.kdf import (
    UNTRUSTED_MAX_MEMORY_COST,
    UNTRUSTED_MAX_TIME_COST,
    KDFParams,
)
from dbs.exceptions import CorruptionError, CryptoError, InvalidPassphrase

KEY = bytes(range(32))
HEADER = b"canonical header bytes"


def cipher(key=KEY, prefix=b"\x01" * NONCE_PREFIX_LENGTH, header=HEADER):
    return ChunkCipher(key, prefix, header)


def test_a_chunk_round_trips():
    sealed = cipher().seal(5, b"payload", final=False)
    assert cipher().open(5, sealed, final=False) == b"payload"


def test_a_chunk_opened_at_another_position_fails():
    sealed = cipher().seal(5, b"payload", final=False)
    with pytest.raises(CorruptionError, match="Chunk 6"):
        cipher().open(6, sealed, final=False)


def test_finality_is_authenticated_so_truncation_is_detected():
    middle = cipher().seal(3, b"not the end", final=False)
    with pytest.raises(CorruptionError):
        cipher().open(3, middle, final=True)
    last = cipher().seal(4, b"the end", final=True)
    with pytest.raises(CorruptionError):
        cipher().open(4, last, final=False)


def test_swapped_chunks_are_detected():
    first = cipher().seal(0, b"first", final=False)
    second = cipher().seal(1, b"second", final=False)
    with pytest.raises(CorruptionError):
        cipher().open(0, second, final=False)
    with pytest.raises(CorruptionError):
        cipher().open(1, first, final=False)


def test_the_header_is_authenticated_with_every_chunk():
    sealed = cipher().seal(0, b"payload", final=True)
    with pytest.raises(CorruptionError):
        cipher(header=HEADER + b"!").open(0, sealed, final=True)


def test_another_stream_prefix_cannot_open_the_chunk():
    sealed = cipher().seal(0, b"payload", final=True)
    with pytest.raises(CorruptionError):
        cipher(prefix=b"\x02" * NONCE_PREFIX_LENGTH).open(0, sealed, final=True)


def test_nonces_combine_prefix_counter_and_finality():
    prefix = new_nonce_prefix()
    assert len(prefix) == NONCE_PREFIX_LENGTH
    nonce = chunk_nonce(prefix, 258, True)
    assert nonce == prefix + b"\x00\x00\x01\x02\x01"
    assert chunk_nonce(prefix, 258, False)[-1] == 0
    with pytest.raises(ValueError):
        chunk_nonce(prefix, 1 << 32, False)
    with pytest.raises(ValueError):
        chunk_nonce(prefix, -1, False)
    with pytest.raises(ValueError):
        chunk_nonce(b"short", 0, False)


def test_a_wrapped_key_needs_the_right_key_and_binding():
    data_key = os.urandom(32)
    nonce, wrapped = wrap_key(KEY, data_key, b"binding")
    assert unwrap_key(KEY, nonce, wrapped, b"binding") == data_key
    with pytest.raises(InvalidPassphrase):
        unwrap_key(os.urandom(32), nonce, wrapped, b"binding")
    with pytest.raises(InvalidPassphrase):
        unwrap_key(KEY, nonce, wrapped, b"other binding")


def test_the_write_defaults_are_within_the_untrusted_bounds():
    KDFParams().validate_untrusted()


@pytest.mark.parametrize(
    "params",
    [
        KDFParams(time_cost=UNTRUSTED_MAX_TIME_COST + 1),
        KDFParams(memory_cost=UNTRUSTED_MAX_MEMORY_COST + 1),
        KDFParams(memory_cost=64, parallelism=16),
        KDFParams(key_length=16),
        KDFParams(time_cost=0),
    ],
)
def test_untrusted_kdf_parameters_beyond_the_bounds_are_refused(params):
    with pytest.raises(CryptoError):
        params.validate_untrusted()
