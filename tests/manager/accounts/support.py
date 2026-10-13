from __future__ import annotations

import time

from dbs.manager.accounts import totp
from dbs.manager.accounts.repositories import AccountRepository
from dbs.manager.accounts.services.two_factor_service import TwoFactorService

SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"


def code(secret: str = SECRET, steps_ahead: int = 0) -> str:
    return totp.code_at(secret, time.time() + steps_ahead * totp.PERIOD)


def enrolled(user, secret: str = SECRET) -> list[str]:
    account = AccountRepository().of(user)
    two_factor = TwoFactorService(account)
    codes = two_factor.enroll(two_factor.sealed(secret), code(secret, -1))
    assert codes is not None
    return codes


def signed_in(client, username: str, password: str, secret: str = SECRET):
    answer = client.post(
        "/api/auth/login/", {"username": username, "password": password}
    )
    assert answer.status_code == 200, answer.content
    assert answer.json() == {"step": "code"}
    done = client.post("/api/auth/two-factor/", {"code": code(secret)})
    assert done.status_code == 200, done.content
    return done
