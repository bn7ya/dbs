from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from dbs.manager.accounts import totp
from dbs.manager.accounts.models import Account
from dbs.manager.accounts.repositories import AccountRepository
from dbs.manager.vault import VaultError, fingerprint, seal_text, unseal_text

ISSUER = "DBS manager"
SECRET_CONTEXT = "accounts.totp"
RECOVERY_CONTEXT = "accounts.recovery"
RECOVERY_CODES = 10
RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
RECOVERY_HALF = 5

logger = logging.getLogger("dbs.manager")


@dataclass(frozen=True)
class Enrollment:
    secret: str
    uri: str
    issuer: str
    username: str


def recovery_code() -> str:
    pick = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(RECOVERY_HALF * 2))
    return f"{pick[:RECOVERY_HALF]}-{pick[RECOVERY_HALF:]}"


def typed_recovery_code(code: str) -> str:
    return "".join(character for character in code.lower() if character.isalnum())


class TwoFactorService:
    def __init__(self, account: Account) -> None:
        self.account = account
        self.accounts = AccountRepository()

    def enrollment(self, secret: str) -> Enrollment:
        username = self.account.user.get_username()
        return Enrollment(
            secret=secret,
            uri=totp.provisioning_uri(secret, username, ISSUER),
            issuer=ISSUER,
            username=username,
        )

    def sealed(self, secret: str) -> bytes:
        return seal_text(secret, context=self._context(SECRET_CONTEXT))

    def opened(self, sealed: bytes) -> str | None:
        try:
            return unseal_text(sealed, context=self._context(SECRET_CONTEXT))
        except VaultError as exc:
            logger.error(
                "the two-factor secret of %s cannot be opened, so its codes are refused: %s",
                self.account.user.get_username(),
                exc,
            )
            return None

    def enroll(self, sealed: bytes, code: str) -> list[str] | None:
        secret = self.opened(sealed)
        if secret is None:
            return None
        step = totp.matching_step(secret, code, time.time())
        if step is None:
            return None
        with transaction.atomic():
            self.accounts.update(
                self.account,
                totp_secret_sealed=sealed,
                totp_enrolled_at=timezone.now(),
                totp_last_step=step,
            )
            return self.new_recovery_codes()

    def verify(self, code: str) -> bool:
        if not self.account.has_two_factor:
            return False
        secret = self.opened(bytes(self.account.totp_secret_sealed))
        if secret is None:
            return False
        step = totp.matching_step(
            secret, code, time.time(), after=self.account.totp_last_step
        )
        return step is not None and self.accounts.claim_step(self.account, step)

    def use_recovery_code(self, code: str) -> bool:
        typed = typed_recovery_code(code)
        if not typed or not self.account.has_two_factor:
            return False
        return self.accounts.use_recovery_code(self.account, self._digest(typed))

    def new_recovery_codes(self) -> list[str]:
        codes = [recovery_code() for _ in range(RECOVERY_CODES)]
        self.accounts.replace_recovery_codes(
            self.account, [self._digest(typed_recovery_code(code)) for code in codes]
        )
        return codes

    def codes_left(self) -> int:
        return self.accounts.recovery_codes_left(self.account)

    def reset(self) -> None:
        self.accounts.forget_two_factor(self.account)

    def _digest(self, typed: str) -> str:
        return fingerprint(
            typed.encode("ascii"), context=self._context(RECOVERY_CONTEXT)
        )

    def _context(self, base: str) -> str:
        return f"{base}:{self.account.pk}"
