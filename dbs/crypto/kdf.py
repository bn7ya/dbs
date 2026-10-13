from __future__ import annotations

from dataclasses import dataclass, asdict

from argon2.low_level import Type, hash_secret_raw

from ..exceptions import CryptoError

KEY_LENGTH = 32

SALT_LENGTH = 16

MAX_TIME_COST = 16

MAX_MEMORY_COST = 1024 * 1024

MAX_PARALLELISM = 16

MIN_KEY_LENGTH = 16

MAX_KEY_LENGTH = 64

UNTRUSTED_MAX_TIME_COST = 10

UNTRUSTED_MAX_MEMORY_COST = 256 * 1024

UNTRUSTED_MAX_PARALLELISM = 16


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
        params = cls(
            time_cost=int(data["time_cost"]),
            memory_cost=int(data["memory_cost"]),
            parallelism=int(data["parallelism"]),
            key_length=int(data.get("key_length", KEY_LENGTH)),
        )
        params.validate()
        return params

    def validate(self) -> None:
        checks = (
            (self.time_cost, 1, MAX_TIME_COST, "time_cost"),
            (self.memory_cost, 8, MAX_MEMORY_COST, "memory_cost"),
            (self.parallelism, 1, MAX_PARALLELISM, "parallelism"),
            (self.key_length, MIN_KEY_LENGTH, MAX_KEY_LENGTH, "key_length"),
        )
        for value, lower, upper, name in checks:
            if not lower <= value <= upper:
                raise CryptoError(
                    f"KDF parameter {name}={value} is outside the accepted "
                    f"range [{lower}, {upper}]."
                )

    def validate_untrusted(self) -> None:
        self.validate()
        ceilings = (
            (self.time_cost, UNTRUSTED_MAX_TIME_COST, "time_cost"),
            (self.memory_cost, UNTRUSTED_MAX_MEMORY_COST, "memory_cost"),
            (self.parallelism, UNTRUSTED_MAX_PARALLELISM, "parallelism"),
        )
        for value, ceiling, name in ceilings:
            if value > ceiling:
                raise CryptoError(
                    f"KDF parameter {name}={value} exceeds {ceiling}, the most a "
                    "backup file may ask for."
                )
        if self.memory_cost < 8 * self.parallelism:
            raise CryptoError(
                f"KDF memory_cost={self.memory_cost} is below 8 KiB per lane "
                f"for parallelism={self.parallelism}."
            )
        if self.key_length != KEY_LENGTH:
            raise CryptoError(f"KDF key_length must be {KEY_LENGTH} for AES-256.")


def derive_key(passphrase: bytes, salt: bytes, params: KDFParams) -> bytes:
    params.validate()
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
