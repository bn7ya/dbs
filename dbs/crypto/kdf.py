from __future__ import annotations

from dataclasses import dataclass, asdict

from argon2.low_level import Type, hash_secret_raw

KEY_LENGTH = 32

SALT_LENGTH = 16


@dataclass(frozen=True)
class KDFParams:
    time_cost: int = 3
    memory_cost: int = 64 * 1024
    parallelism: int = 4
    key_length: int = KEY_LENGTH

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "KDFParams":
        return cls(
            time_cost=int(data["time_cost"]),
            memory_cost=int(data["memory_cost"]),
            parallelism=int(data["parallelism"]),
            key_length=int(data.get("key_length", KEY_LENGTH)),
        )


def derive_key(passphrase: bytes, salt: bytes, params: KDFParams) -> bytes:
    if isinstance(passphrase, str):
        passphrase = passphrase.encode("utf-8")
    return hash_secret_raw(
        secret=passphrase,
        salt=salt,
        time_cost=params.time_cost,
        memory_cost=params.memory_cost,
        parallelism=params.parallelism,
        hash_len=params.key_length,
        type=Type.ID,
    )
