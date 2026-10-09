from __future__ import annotations

import base64
import hashlib

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

KEY_COMMENT = "django-dbs"


class KeyUnreadable(ValueError):
    pass


def generate_keypair() -> tuple[str, str]:
    private = Ed25519PrivateKey.generate()
    pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption(),
    ).decode("ascii")
    return pem, _public_line(private)


def public_key_of(private_key: str, passphrase: str | None = None) -> str:
    secret = passphrase.encode() if passphrase else None
    data = private_key.encode()
    loaders = (serialization.load_ssh_private_key, serialization.load_pem_private_key)
    for load in loaders:
        try:
            return _public_line(load(data, password=secret))
        except (ValueError, TypeError):
            continue
    raise KeyUnreadable("The stored private key could not be read.")


def fingerprint(public_line: str) -> str:
    blob = base64.b64decode(public_line.split()[1])
    digest = hashlib.sha256(blob).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


def authorized_keys_hint(public_line: str, username: str) -> str:
    return f"echo '{public_line}' >> ~{username}/.ssh/authorized_keys"


def _public_line(private) -> str:
    public = private.public_key().public_bytes(
        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
    )
    return f"{public.decode('ascii')} {KEY_COMMENT}"
