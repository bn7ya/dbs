from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth import logout
from django.contrib.auth.models import AnonymousUser, User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed, ErrorDetail, ValidationError
from rest_framework.request import Request

from dbs.manager import permissions
from dbs.manager.accounts import throttle
from dbs.manager.accounts.exceptions import InvalidPassword, TooManyAttempts
from dbs.manager.accounts.models import Account
from dbs.manager.accounts.repositories import AccountRepository, UserRepository
from dbs.manager.accounts.services.two_factor_service import TwoFactorService
from dbs.manager.activity.services import ActivityService

INVALID_CREDENTIALS: str = "That username and password don't match an account."
INACTIVE_ACCOUNT: str = "This account has been deactivated. Contact an administrator."
PASSWORD_UNCHANGED: str = "Choose a password you have not been using."


class Action:
    SIGN_IN = "auth.sign_in"
    SIGN_IN_FAILED = "auth.sign_in_failed"
    SIGN_OUT = "auth.sign_out"
    PASSWORD = "account.password"
    RECOVERY_CODES = "account.recovery_codes"


def password_errors(exc: DjangoValidationError) -> list[ErrorDetail]:
    return [
        ErrorDetail(" ".join(error.messages), code=error.code or "password_invalid")
        for error in exc.error_list
    ]


def password_max_age() -> timedelta:
    return timedelta(days=settings.AUTH_PASSWORD_MAX_AGE_DAYS)


class AccountService:
    def __init__(self, user: User | AnonymousUser | None = None) -> None:
        self.user: User | AnonymousUser | None = user
        self.users: UserRepository = UserRepository()
        self.accounts: AccountRepository = AccountRepository()

    def sign_out(self, request: Request) -> None:
        if self.user is not None and self.user.is_authenticated:
            ActivityService(self.user).record(
                Action.SIGN_OUT, target=self.user.get_username()
            )
        logout(request)

    def confirm_password(self, password: str) -> None:
        if self.user is None or not self.user.is_authenticated:
            raise InvalidPassword()
        key = f"confirm:user:{self.user.pk}"
        if not throttle.counted(((key, settings.AUTH_FAILURES_PER_USER),)):
            throttle.given_back((key,))
            raise TooManyAttempts()
        if not self.user.check_password(password):
            raise InvalidPassword()
        throttle.cleared((key,))

    def account(self) -> Account:
        return self.accounts.of(self._signed_in())

    def password_expires_at(self, account: Account | None = None) -> datetime:
        account = account or self.account()
        return account.password_changed_at + password_max_age()

    def password_expired(self, account: Account | None = None) -> bool:
        return self.password_expires_at(account) <= timezone.now()

    def password_change_required(self) -> bool:
        if not isinstance(self.user, User) or not self.user.is_authenticated:
            return False
        account = self.accounts.find(self.user.pk)
        if account is None:
            return False
        return account.password_change_required or self.password_expired(account)

    def change_password(self, current_password: str, new_password: str) -> User:
        user = self._signed_in()
        self.confirm_password(current_password)
        if user.check_password(new_password):
            raise ValidationError(
                {
                    "new_password": [
                        ErrorDetail(PASSWORD_UNCHANGED, code="password_unchanged")
                    ]
                }
            )
        try:
            validate_password(new_password, user=user)
        except DjangoValidationError as exc:
            raise ValidationError({"new_password": password_errors(exc)}) from exc
        self.users.set_password(user, new_password)
        ActivityService(user).record(Action.PASSWORD, target=user.get_username())
        return user

    def new_recovery_codes(self, password: str) -> list[str]:
        user = self._signed_in()
        self.confirm_password(password)
        codes = TwoFactorService(self.accounts.of(user)).new_recovery_codes()
        ActivityService(user).record(Action.RECOVERY_CODES, target=user.get_username())
        return codes

    def identity(self) -> dict[str, Any]:
        signed_in = self._signed_in()
        user: User = self.users.with_groups(signed_in.pk) or signed_in
        account = self.accounts.of(user)
        role = permissions.role_of(user)

        return {
            "id": user.pk,
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "is_staff": user.is_staff,
            "is_superuser": user.is_superuser,
            "groups": self.users.group_names(user),
            "permissions": self.users.permission_codenames(user),
            "role": role,
            "capabilities": permissions.capabilities(role),
            "two_factor": account.has_two_factor,
            "recovery_codes_left": TwoFactorService(account).codes_left(),
            "password_changed_at": account.password_changed_at,
            "password_expires_at": self.password_expires_at(account),
            "password_change_required": account.password_change_required
            or self.password_expired(account),
        }

    def has_group(self, name: str) -> bool:
        if not isinstance(self.user, User) or not self.user.is_authenticated:
            return False
        if self.user.is_superuser:
            return True
        return self.users.in_group(self.user, name)

    def _signed_in(self) -> User:
        if not isinstance(self.user, User) or not self.user.is_authenticated:
            raise AuthenticationFailed(INVALID_CREDENTIALS)
        return self.user
