from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct
import time
from urllib.parse import quote, urlencode

DIGITS = 6
PERIOD = 30
DRIFT_STEPS = 1
SECRET_BYTES = 20
ALGORITHM = "SHA1"


def new_secret() -> str:
    return base64.b32encode(os.urandom(SECRET_BYTES)).decode("ascii").rstrip("=")


def secret_bytes(secret: str) -> bytes:
    cleaned = "".join(secret.split()).upper()
    return base64.b32decode(cleaned + "=" * (-len(cleaned) % 8))


def hotp(key: bytes, counter: int, digits: int = DIGITS) -> str:
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10**digits).zfill(digits)


def step_at(moment: float) -> int:
    return int(moment // PERIOD)


def code_at(secret: str, moment: float) -> str:
    return hotp(secret_bytes(secret), step_at(moment))


def normalised(code: str) -> str:
    return "".join(code.split())


def matching_step(
    secret: str, code: str, moment: float | None = None, after: int | None = None
) -> int | None:
    typed = normalised(code)
    if len(typed) != DIGITS or not typed.isdigit():
        return None
    key = secret_bytes(secret)
    current = step_at(time.time() if moment is None else moment)
    for step in range(current - DRIFT_STEPS, current + DRIFT_STEPS + 1):
        if after is not None and step <= after:
            continue
        if hmac.compare_digest(hotp(key, step), typed):
            return step
    return None


def provisioning_uri(secret: str, account: str, issuer: str) -> str:
    label = quote(f"{issuer}:{account}", safe="")
    query = urlencode(
        {
            "secret": secret,
            "issuer": issuer,
            "algorithm": ALGORITHM,
            "digits": DIGITS,
            "period": PERIOD,
        }
    )
    return f"otpauth://totp/{label}?{query}"
