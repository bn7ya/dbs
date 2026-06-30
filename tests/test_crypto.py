"""Crypto layer: envelope round-trip, brute-force surface, secret hygiene."""

import os

import pytest

from dbs.crypto import decrypt_payload, encrypt_payload
from dbs.crypto.kdf import KDFParams, derive_key
from dbs.exceptions import InvalidPassphrase

FAST = KDFParams(time_cost=1, memory_cost=8 * 1024, parallelism=1)


def test_roundtrip():
    plaintext = os.urandom(4096)
    ciphertext, material = encrypt_payload(plaintext, "correct horse", kdf_params=FAST)
    assert ciphertext != plaintext
    assert decrypt_payload(ciphertext, "correct horse", material) == plaintext


def test_wrong_passphrase_rejected():
    ciphertext, material = encrypt_payload(b"secret data", "right", kdf_params=FAST)
    with pytest.raises(InvalidPassphrase):
        decrypt_payload(ciphertext, "wrong", material)


def test_tampered_wrapped_key_rejected():
    ciphertext, material = encrypt_payload(b"secret data", "pw", kdf_params=FAST)
    tampered = bytearray(material.wrapped_dek)
    tampered[0] ^= 0x01
    material.wrapped_dek = bytes(tampered)
    with pytest.raises(InvalidPassphrase):
        decrypt_payload(ciphertext, "pw", material)


def test_kdf_is_deterministic_and_salted():
    salt = os.urandom(16)
    k1 = derive_key(b"pw", salt, FAST)
    k2 = derive_key(b"pw", salt, FAST)
    k3 = derive_key(b"pw", os.urandom(16), FAST)
    assert k1 == k2 and k1 != k3 and len(k1) == 32


def test_passphrase_and_dek_absent_from_serialized_material():
    passphrase = "super-secret-phrase-12345"
    ciphertext, material = encrypt_payload(b"x" * 1000, passphrase, kdf_params=FAST)
    blob = repr(material.to_dict()).encode() + ciphertext
    assert passphrase.encode() not in blob
