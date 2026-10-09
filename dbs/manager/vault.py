from __future__ import annotations

import hashlib
import hmac
import os
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.core.exceptions import ImproperlyConfigured

from dbs.keys import _secret_keys

if TYPE_CHECKING:
    from _typeshed import SupportsRead

VERSION = b"\x01"
KEY_ID_BYTES = 4
NONCE_BYTES = 12
TAG_BYTES = 16
KEY_BYTES = 32
HEADER_BYTES = len(VERSION) + KEY_ID_BYTES

VAULT_INFO = b"django-dbs/manager-vault/v1"
KEY_ID_INFO = b"django-dbs/manager-vault/key-id\x00"
STREAM_MAGIC = b"DBSMSEAL"
STREAM_VERSION = b"\x01"
CHUNK_SIZE_BYTES = 4
BASE_NONCE_BYTES = 7
COUNTER_BYTES = 4
WRAPPED_KEY_BYTES = KEY_BYTES + TAG_BYTES
STREAM_HEADER_BYTES = (
    len(STREAM_MAGIC)
    + len(STREAM_VERSION)
    + KEY_ID_BYTES
    + CHUNK_SIZE_BYTES
    + BASE_NONCE_BYTES
    + NONCE_BYTES
    + WRAPPED_KEY_BYTES
)
CHUNK_BYTES = 1024 * 1024
MAX_CHUNK_BYTES = 64 * 1024 * 1024
LAST_CHUNK = b"\x01"
NOT_LAST_CHUNK = b"\x00"
FINGERPRINT_INFO = b"django-dbs/manager-vault/fingerprint\x00"


class VaultError(Exception):
    pass


@dataclass(frozen=True)
class SealedStream:
    size: int
    sha256: str


def _derive(secret: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(), length=KEY_BYTES, salt=None, info=VAULT_INFO
    ).derive(secret)


def _keys() -> list[bytes]:
    keys = [_derive(secret) for secret in _secret_keys()]
    if not keys:
        raise ImproperlyConfigured(
            "SECRET_KEY is empty; nothing can be sealed or opened."
        )
    return keys


def _key_id(key: bytes) -> bytes:
    return hashlib.sha256(KEY_ID_INFO + key).digest()[:KEY_ID_BYTES]


def seal(plaintext: bytes, *, context: str) -> bytes:
    key = _keys()[0]
    header = VERSION + _key_id(key)
    nonce = os.urandom(NONCE_BYTES)
    return (
        header
        + nonce
        + AESGCM(key).encrypt(nonce, plaintext, header + context.encode())
    )


def unseal(token: bytes | memoryview, *, context: str) -> bytes:
    token = bytes(token)
    if len(token) < HEADER_BYTES + NONCE_BYTES + TAG_BYTES or token[:1] != VERSION:
        raise VaultError("This value was not sealed by the vault.")
    header = token[:HEADER_BYTES]
    key = next((k for k in _keys() if _key_id(k) == header[1:]), None)
    if key is None:
        raise VaultError(
            "This value was sealed with a key this data directory no longer holds."
        )
    nonce = token[HEADER_BYTES : HEADER_BYTES + NONCE_BYTES]
    try:
        return AESGCM(key).decrypt(
            nonce, token[HEADER_BYTES + NONCE_BYTES :], header + context.encode()
        )
    except InvalidTag as exc:
        raise VaultError(
            "This value did not open: it was altered or sealed for another use."
        ) from exc


def seal_text(plaintext: str, *, context: str) -> bytes:
    return seal(plaintext.encode("utf-8"), context=context)


def fingerprint(data: bytes, *, context: str) -> str:
    subkey = HKDF(
        algorithm=hashes.SHA256(),
        length=KEY_BYTES,
        salt=None,
        info=FINGERPRINT_INFO + context.encode(),
    ).derive(_keys()[0])
    return hmac.new(subkey, data, hashlib.sha256).hexdigest()


def unseal_text(token: bytes | memoryview, *, context: str) -> str:
    return unseal(token, context=context).decode("utf-8")


def seal_stream(
    source: SupportsRead[bytes], target: BinaryIO, *, context: str
) -> SealedStream:
    key = _keys()[0]
    base = os.urandom(BASE_NONCE_BYTES)
    key_nonce = os.urandom(NONCE_BYTES)
    authenticated = (
        STREAM_MAGIC
        + STREAM_VERSION
        + _key_id(key)
        + CHUNK_BYTES.to_bytes(CHUNK_SIZE_BYTES, "big")
        + base
        + key_nonce
    )
    file_key = AESGCM.generate_key(bit_length=KEY_BYTES * 8)
    wrapped = AESGCM(key).encrypt(key_nonce, file_key, authenticated + context.encode())
    header = authenticated + wrapped
    target.write(header)

    cipher = AESGCM(file_key)
    digest = hashlib.sha256()
    size = 0
    index = 0
    chunk = _read_full(source, CHUNK_BYTES)
    while True:
        following = _read_full(source, CHUNK_BYTES)
        last = not following
        digest.update(chunk)
        size += len(chunk)
        target.write(
            cipher.encrypt(_chunk_nonce(base, index, last=last), chunk, header)
        )
        if last:
            return SealedStream(size=size, sha256=digest.hexdigest())
        chunk = following
        index += 1


def open_stream(source: BinaryIO, *, context: str) -> Iterator[bytes]:
    header = _read_full(source, STREAM_HEADER_BYTES)
    if len(header) != STREAM_HEADER_BYTES or not header.startswith(
        STREAM_MAGIC + STREAM_VERSION
    ):
        raise VaultError("This file was not sealed by the vault.")
    authenticated, wrapped = header[:-WRAPPED_KEY_BYTES], header[-WRAPPED_KEY_BYTES:]
    offset = len(STREAM_MAGIC) + len(STREAM_VERSION)
    key_id = authenticated[offset : offset + KEY_ID_BYTES]
    offset += KEY_ID_BYTES
    chunk_bytes = int.from_bytes(
        authenticated[offset : offset + CHUNK_SIZE_BYTES], "big"
    )
    offset += CHUNK_SIZE_BYTES
    base = authenticated[offset : offset + BASE_NONCE_BYTES]
    key_nonce = authenticated[-NONCE_BYTES:]

    key = next((k for k in _keys() if _key_id(k) == key_id), None)
    if key is None:
        raise VaultError(
            "This file was sealed with a key this data directory no longer holds."
        )
    try:
        file_key = AESGCM(key).decrypt(
            key_nonce, wrapped, authenticated + context.encode()
        )
    except InvalidTag as exc:
        raise VaultError(
            "This file did not open: it was altered or sealed for another use."
        ) from exc
    if not 0 < chunk_bytes <= MAX_CHUNK_BYTES:
        raise VaultError("This sealed file claims an impossible chunk size.")
    return _records(source, AESGCM(file_key), base, header, chunk_bytes + TAG_BYTES)


def _records(
    source: BinaryIO, cipher: AESGCM, base: bytes, header: bytes, record_bytes: int
) -> Iterator[bytes]:
    index = 0
    record = _read_full(source, record_bytes)
    while True:
        if len(record) < TAG_BYTES:
            raise VaultError("This sealed file is cut short.")
        following = _read_full(source, record_bytes)
        last = not following
        try:
            chunk = cipher.decrypt(_chunk_nonce(base, index, last=last), record, header)
        except InvalidTag as exc:
            raise VaultError(
                "This sealed file was altered, reordered or cut short."
            ) from exc
        if chunk:
            yield chunk
        if last:
            return
        record = following
        index += 1


def _chunk_nonce(base: bytes, index: int, *, last: bool) -> bytes:
    if index >= 2 ** (COUNTER_BYTES * 8):
        raise VaultError("This file is too large to seal.")
    return (
        base
        + index.to_bytes(COUNTER_BYTES, "big")
        + (LAST_CHUNK if last else NOT_LAST_CHUNK)
    )


def _read_full(source: SupportsRead[bytes], size: int) -> bytes:
    parts = []
    remaining = size
    while remaining:
        part = source.read(remaining)
        if not part:
            break
        parts.append(part)
        remaining -= len(part)
    return b"".join(parts)
