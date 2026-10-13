from __future__ import annotations

import base64
import time
from typing import Any

from django.conf import settings

from dbs.manager.accounts.exceptions import SignInExpired
from dbs.manager.accounts.repositories import UserRepository

USER = "dbs_manager.sign_in.user"
SINCE = "dbs_manager.sign_in.since"
ENROLLING = "dbs_manager.sign_in.enrolling"
KEYS = (USER, SINCE, ENROLLING)


class PendingSignIn:
    def __init__(self, request: Any) -> None:
        self.session = request.session

    def begin(self, user: Any) -> None:
        self.end()
        self.session.cycle_key()
        self.session[USER] = user.pk
        self.session[SINCE] = time.time()

    def user(self) -> Any:
        since = self.session.get(SINCE)
        user_id = self.session.get(USER)
        if (
            user_id is None
            or since is None
            or time.time() - since > settings.AUTH_PENDING_SECONDS
        ):
            self.end()
            raise SignInExpired()
        user = UserRepository().find_active(user_id)
        if user is None:
            self.end()
            raise SignInExpired()
        return user

    def hold(self, sealed: bytes) -> None:
        self.session[ENROLLING] = base64.b64encode(sealed).decode("ascii")

    def held(self) -> bytes | None:
        value = self.session.get(ENROLLING)
        return None if value is None else base64.b64decode(value)

    def end(self) -> None:
        for key in KEYS:
            self.session.pop(key, None)
