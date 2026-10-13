from __future__ import annotations

import os
import struct

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..exceptions import CorruptionError, InvalidPassphrase

KEY_LENGTH = 32

NONCE_LENGTH = 12

NONCE_PREFIX_LENGTH = 7

TAG_LENGTH = 16

WRAPPED_KEY_LENGTH = KEY_LENGTH + TAG_LENGTH

MAX_CHUNKS = 1 << 32

_COUNTER = struct.Struct(">IB")

_WRAP_LABEL = b"dbs/v2/key-wrap\x00"

_FINAL = 1


def new_nonce_prefix() -> bytes:
    return os.urandom(NONCE_PREFIX_LENGTH)


def chunk_nonce(prefix: bytes, index: int, final: bool) -> bytes:
    if len(prefix) != NONCE_PREFIX_LENGTH:
        raise ValueError(f"The nonce prefix must be {NONCE_PREFIX_LENGTH} bytes.")
    if not 0 <= index < MAX_CHUNKS:
        raise ValueError(f"Chunk index {index} is outside [0, {MAX_CHUNKS}).")
    return prefix + _COUNTER.pack(index, _FINAL if final else 0)


class ChunkCipher:
    def __init__(self, key: bytes, nonce_prefix: bytes, associated_data: bytes):
        if len(key) != KEY_LENGTH:
            raise ValueError(f"The data key must be {KEY_LENGTH} bytes.")
        self._aead = AESGCM(key)
        self._prefix = bytes(nonce_prefix)
        self._associated_data = bytes(associated_data)

    def seal(self, index: int, plaintext: bytes, *, final: bool) -> bytes:
        nonce = chunk_nonce(self._prefix, index, final)
        return self._aead.encrypt(nonce, plaintext, self._associated_data)

    def open(self, index: int, ciphertext: bytes, *, final: bool) -> bytes:
        nonce = chunk_nonce(self._prefix, index, final)
        try:
            return self._aead.decrypt(nonce, ciphertext, self._associated_data)
        except InvalidTag as exc:
            raise CorruptionError(
                f"Chunk {index} failed authentication: the backup was altered, "
                "reordered or cut short."
            ) from exc


def wrap_key(kek: bytes, dek: bytes, associated_data: bytes) -> tuple[bytes, bytes]:
    nonce = os.urandom(NONCE_LENGTH)
    wrapped = AESGCM(kek).encrypt(nonce, dek, _WRAP_LABEL + associated_data)
    return nonce, wrapped


def unwrap_key(kek: bytes, nonce: bytes, wrapped: bytes, associated_data: bytes) -> bytes:
    try:
        dek = AESGCM(kek).decrypt(nonce, wrapped, _WRAP_LABEL + associated_data)
    except InvalidTag as exc:
        raise InvalidPassphrase(
            "Could not unwrap the data key: wrong passphrase or tampered key material."
        ) from exc
    if len(dek) != KEY_LENGTH:
        raise InvalidPassphrase("The unwrapped data key has the wrong length.")
    return dek
