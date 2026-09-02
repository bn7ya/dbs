from __future__ import annotations

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..exceptions import ConfigurationError, InvalidPassphrase
from ..keys import derive_field_keys

PREFIX = "dbs1:"

NONCE_LENGTH = 12

AAD = b"dbs/field/v1"


def is_encrypted(value: str | None) -> bool:
    return bool(value) and value.startswith(PREFIX)


def encrypt_secret(plaintext: str) -> str:
    keys = derive_field_keys()
    if not keys:
        raise ConfigurationError(
            "Storing a credential needs SECRET_KEY, which is not set."
        )
    nonce = os.urandom(NONCE_LENGTH)
    sealed = AESGCM(keys[0]).encrypt(nonce, plaintext.encode("utf-8"), AAD)
    return PREFIX + base64.b64encode(nonce + sealed).decode("ascii")


def decrypt_secret(token: str) -> str:
    if not is_encrypted(token):
        raise InvalidPassphrase("Value is not a DBS-encrypted credential.")
    try:
        raw = base64.b64decode(token[len(PREFIX):].encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise InvalidPassphrase("Credential is not valid base64.") from exc
    if len(raw) <= NONCE_LENGTH:
        raise InvalidPassphrase("Credential is truncated.")
    nonce, sealed = raw[:NONCE_LENGTH], raw[NONCE_LENGTH:]
    for key in derive_field_keys():
        try:
            return AESGCM(key).decrypt(nonce, sealed, AAD).decode("utf-8")
        except (InvalidTag, UnicodeDecodeError):
            continue
    raise InvalidPassphrase(
        "Credential cannot be read with the current SECRET_KEY. It was stored "
        "under a different key; add the old one to SECRET_KEY_FALLBACKS or "
        "re-enter the credential."
    )


def read_secret(token: str | None) -> str | None:
    if not token:
        return None
    return decrypt_secret(token)
