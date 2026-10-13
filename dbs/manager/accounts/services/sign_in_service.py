from __future__ import annotations

from typing import Any, NoReturn

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from rest_framework.exceptions import AuthenticationFailed

from dbs import audit
from dbs.manager.accounts import throttle
from dbs.manager.accounts.exceptions import (
    InvalidCode,
    TooManyAttempts,
    TwoFactorEnrolled,
    TwoFactorMissing,
)
from dbs.manager.accounts.repositories import AccountRepository, UserRepository
from dbs.manager.accounts.services.account_service import (
    INACTIVE_ACCOUNT,
    INVALID_CREDENTIALS,
    Action,
)
from dbs.manager.accounts.services.pending import PendingSignIn
from dbs.manager.accounts.services.two_factor_service import (
    Enrollment,
    TwoFactorService,
)
from dbs.manager.accounts.totp import new_secret
from dbs.manager.activity.services import ActivityService
from dbs.manager.common.exceptions import error_code_of
from dbs.manager.middleware import current_ip

ENROLLED = "account.two_factor_enrolled"
RECOVERY_CODE_USED = "auth.recovery_code_used"


class Step:
    CODE = "code"
    ENROLL = "enroll"


class SignInService:
    def __init__(self, request: Any) -> None:
        self.request = request
        self.pending = PendingSignIn(request)
        self.users = UserRepository()
        self.accounts = AccountRepository()

    def password(self, username: str, password: str) -> str:
        name = username.casefold()
        address = current_ip() or "unknown"
        pair = f"sign-in:pair:{address}:{name}"
        by_address = f"sign-in:address:{address}"
        by_name = f"sign-in:name:{name}"

        if not throttle.known(name, address):
            wait = throttle.waiting(by_name)
            if wait:
                self._refuse(username, TooManyAttempts(wait))
        limits = (
            (pair, settings.AUTH_FAILURES_PER_USER),
            (by_address, settings.AUTH_FAILURES_PER_ADDRESS),
        )
        if not throttle.counted(limits):
            throttle.given_back((pair, by_address))
            self._refuse(username, TooManyAttempts())

        user: User | None = authenticate(
            request=None, username=username, password=password
        )
        if user is None:
            throttle.slowed(by_name, settings.AUTH_FAILURES_PER_USER)
            refused = AuthenticationFailed(INVALID_CREDENTIALS)
            existing: User | None = self.users.find_by_username(username)
            if existing is not None and not existing.is_active:
                refused = AuthenticationFailed(INACTIVE_ACCOUNT)
            self._refuse(username, refused)

        throttle.cleared((pair,))
        throttle.given_back((by_address,))
        return self.begin(user)

    def begin(self, user: User) -> str:
        if self.request.user.is_authenticated:
            logout(self.request)
        self.pending.begin(user)
        return Step.CODE if self.accounts.of(user).has_two_factor else Step.ENROLL

    def second_factor(self, code: str = "", recovery_code: str = "") -> User:
        user = self.pending.user()
        account = self.accounts.of(user)
        if not account.has_two_factor:
            raise TwoFactorMissing()
        self._count_code(user)
        two_factor = TwoFactorService(account)
        if recovery_code:
            accepted = two_factor.use_recovery_code(recovery_code)
        else:
            accepted = two_factor.verify(code)
        if not accepted:
            self._refuse(user.get_username(), InvalidCode())
        if recovery_code:
            ActivityService(user).record(RECOVERY_CODE_USED, target=user.get_username())
        return self._complete(user)

    def enrollment(self) -> Enrollment:
        user = self.pending.user()
        account = self.accounts.of(user)
        if account.has_two_factor:
            raise TwoFactorEnrolled()
        two_factor = TwoFactorService(account)
        sealed = self.pending.held()
        secret = None if sealed is None else two_factor.opened(sealed)
        if secret is None:
            secret = new_secret()
            self.pending.hold(two_factor.sealed(secret))
        return two_factor.enrollment(secret)

    def enroll(self, code: str) -> tuple[User, list[str]]:
        user = self.pending.user()
        account = self.accounts.of(user)
        if account.has_two_factor:
            raise TwoFactorEnrolled()
        sealed = self.pending.held()
        if sealed is None:
            raise InvalidCode()
        self._count_code(user)
        codes = TwoFactorService(account).enroll(sealed, code)
        if codes is None:
            self._refuse(user.get_username(), InvalidCode())
        ActivityService(user).record(ENROLLED, target=user.get_username())
        return self._complete(user), codes

    def _count_code(self, user: User) -> None:
        address = current_ip() or "unknown"
        limits = (
            (f"code:user:{user.pk}", settings.AUTH_FAILURES_PER_USER),
            (f"code:address:{address}", settings.AUTH_FAILURES_PER_ADDRESS),
        )
        if not throttle.counted(limits):
            throttle.given_back([name for name, _ in limits])
            self._refuse(user.get_username(), TooManyAttempts())

    def _complete(self, user: User) -> User:
        address = current_ip() or "unknown"
        name = user.get_username().casefold()
        self.pending.end()
        throttle.cleared((f"code:user:{user.pk}",))
        throttle.given_back((f"code:address:{address}",))
        throttle.unslowed(f"sign-in:name:{name}")
        throttle.remember(name, address)
        login(self.request, user, backend=settings.AUTHENTICATION_BACKENDS[0])
        ActivityService(user).record(Action.SIGN_IN, target=user.get_username())
        return user

    def _refuse(self, username: str, refused: Exception) -> NoReturn:
        ActivityService(None).record(
            Action.SIGN_IN_FAILED,
            target=username,
            status=audit.FAILED,
            error_code=error_code_of(refused),
        )
        raise refused
