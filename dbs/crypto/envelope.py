from __future__ import annotations

import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..exceptions import InvalidPassphrase
from .kdf import KDFParams, SALT_LENGTH, derive_key

NONCE_LENGTH = 12

_DEK_AAD = b"dbs/dek-wrap/v1"
_DATA_AAD = b"dbs/data/v1"


def _b64(value: bytes) -> str:
    import base64

    return base64.b64encode(value).decode("ascii")


def _unb64(value: str) -> bytes:
    import base64

    return base64.b64decode(value.encode("ascii"))


@dataclass
class EnvelopeMaterial:
    salt: bytes
    kdf_params: KDFParams
    wrapped_dek: bytes
    dek_nonce: bytes
    data_nonce: bytes

    def to_dict(self) -> dict:
        return {
            "kdf": "argon2id",
            "salt": _b64(self.salt),
            "params": self.kdf_params.to_dict(),
            "wrapped_dek": _b64(self.wrapped_dek),
            "dek_nonce": _b64(self.dek_nonce),
            "data_nonce": _b64(self.data_nonce),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EnvelopeMaterial":
        return cls(
            salt=_unb64(data["salt"]),
            kdf_params=KDFParams.from_dict(data["params"]),
            wrapped_dek=_unb64(data["wrapped_dek"]),
            dek_nonce=_unb64(data["dek_nonce"]),
            data_nonce=_unb64(data["data_nonce"]),
        )


def generate_dek() -> bytes:
    return AESGCM.generate_key(bit_length=256)


def encrypt_payload(
    plaintext: bytes,
    passphrase: str | bytes,
    *,
    kdf_params: KDFParams | None = None,
) -> tuple[bytes, EnvelopeMaterial]:
    params = kdf_params or KDFParams()
    salt = os.urandom(SALT_LENGTH)
    kek = derive_key(_as_bytes(passphrase), salt, params)

    dek = generate_dek()
    data_nonce = os.urandom(NONCE_LENGTH)
    ciphertext = AESGCM(dek).encrypt(data_nonce, plaintext, _DATA_AAD)

    dek_nonce = os.urandom(NONCE_LENGTH)
    wrapped_dek = AESGCM(kek).encrypt(dek_nonce, dek, _DEK_AAD)

    material = EnvelopeMaterial(
        salt=salt,
        kdf_params=params,
        wrapped_dek=wrapped_dek,
        dek_nonce=dek_nonce,
        data_nonce=data_nonce,
    )
    return ciphertext, material


def decrypt_payload(
    ciphertext: bytes,
    passphrase: str | bytes,
    material: EnvelopeMaterial,
) -> bytes:
    kek = derive_key(_as_bytes(passphrase), material.salt, material.kdf_params)
    try:
        dek = AESGCM(kek).decrypt(material.dek_nonce, material.wrapped_dek, _DEK_AAD)
    except InvalidTag as exc:
        raise InvalidPassphrase(
            "Could not unwrap the data key: wrong passphrase or tampered key material."
        ) from exc
    try:
        return AESGCM(dek).decrypt(material.data_nonce, ciphertext, _DATA_AAD)
    except InvalidTag as exc:
        raise InvalidPassphrase(
            "Data key was valid but the ciphertext failed authentication (corrupted)."
        ) from exc


def _as_bytes(value: str | bytes) -> bytes:
    return value.encode("utf-8") if isinstance(value, str) else value
