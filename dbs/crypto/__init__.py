"""Cryptography layer: Argon2id key derivation and AES-256-GCM envelope encryption.

Nothing in here rolls its own primitives -- key derivation comes from
``argon2-cffi`` and the AEAD comes from ``cryptography`` (pyca). The envelope
scheme keeps the *memorized passphrase* and the *raw data key* out of the
backup file entirely; only a salt, the Argon2 parameters and the
passphrase-wrapped data key are persisted.
"""

from .envelope import (
    EnvelopeMaterial,
    decrypt_payload,
    encrypt_payload,
    generate_dek,
)
from .kdf import KDFParams, derive_key

__all__ = [
    "KDFParams",
    "derive_key",
    "EnvelopeMaterial",
    "encrypt_payload",
    "decrypt_payload",
    "generate_dek",
]
