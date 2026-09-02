from __future__ import annotations

import base64
import hashlib
import hmac

from .conf import setting
from .exceptions import ConfigurationError, InvalidPassphrase

BACKUP_INFO = b"django-dbs/backup-passphrase/v1"

FIELD_INFO = b"django-dbs/field-encryption/v1"

ENV_VAR = "DBS_PASSPHRASE"


def _hkdf(secret: bytes, info: bytes, length: int) -> bytes:
    prk = hmac.new(b"django-dbs", secret, hashlib.sha256).digest()
    output = b""
    block = b""
    counter = 1
    while len(output) < length:
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        output += block
        counter += 1
    return output[:length]


def _as_bytes(value) -> bytes:
    if isinstance(value, bytes):
        return value
    return str(value).encode("utf-8")


def _secret_keys() -> list[bytes]:
    current = setting("SECRET_KEY", None)
    keys = [_as_bytes(current)] if current else []
    for fallback in setting("SECRET_KEY_FALLBACKS", None) or ():
        if fallback:
            keys.append(_as_bytes(fallback))
    return keys


def derive_field_keys() -> list[bytes]:
    return [_hkdf(key, FIELD_INFO, 32) for key in _secret_keys()]


def derive_passphrase(secret_key) -> str:
    raw = _hkdf(_as_bytes(secret_key), BACKUP_INFO, 32)
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def default_passphrase() -> str:
    """Return the backup passphrase DBS derives from Django's ``SECRET_KEY``."""
    keys = _secret_keys()
    if not keys:
        raise ConfigurationError(
            "DBS derives its backup passphrase from SECRET_KEY, which is not set. "
            f"Set SECRET_KEY, or give a passphrase explicitly via ${ENV_VAR}."
        )
    return derive_passphrase(keys[0])


def candidate_passphrases() -> list[str]:
    return [derive_passphrase(key) for key in _secret_keys()]


def has_default_passphrase() -> bool:
    return bool(_secret_keys())


def with_passphrase(action, passphrase: str | None = None):
    candidates = [passphrase] if passphrase else candidate_passphrases()
    if not candidates:
        raise ConfigurationError(
            "No passphrase was given and SECRET_KEY is not set, so DBS cannot "
            "derive one."
        )
    failure = None
    for candidate in candidates:
        try:
            return action(candidate)
        except InvalidPassphrase as exc:
            failure = exc
    raise failure
