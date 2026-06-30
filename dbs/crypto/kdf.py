"""Argon2id key derivation.

Argon2id (RFC 9106) is a memory-hard KDF: legitimate users derive the key once,
while an attacker brute-forcing the passphrase must pay the full memory + time
cost on every guess. That memory-hardness is the "brute-force resistance" the
backup format relies on, since the passphrase itself is never stored.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

from argon2.low_level import Type, hash_secret_raw

# Length of the derived key in bytes (256-bit key for AES-256-GCM).
KEY_LENGTH = 32

# Length of the random salt in bytes. The salt is *not* secret and is stored in
# the manifest; it only needs to be unique per backup.
SALT_LENGTH = 16


@dataclass(frozen=True)
class KDFParams:
    """Tunable Argon2id cost parameters.

    Defaults target roughly the interactive RFC 9106 recommendation while
    keeping the test-suite fast. Raise ``memory_cost``/``time_cost`` for more
    brute-force resistance at the cost of slower backup/restore.
    """

    time_cost: int = 3
    memory_cost: int = 64 * 1024  # KiB -> 64 MiB
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
    """Derive a key-encryption-key (KEK) from ``passphrase`` and ``salt``."""
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
