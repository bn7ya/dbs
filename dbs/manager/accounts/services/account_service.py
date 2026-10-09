from __future__ import annotations

from typing import Any, NoReturn

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import AnonymousUser, User
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from dbs import audit
from dbs.manager.accounts import throttle
from dbs.manager.accounts.exceptions import InvalidPassword, TooManyAttempts
from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.activity.services import ActivityService
from dbs.manager.common.exceptions import error_code_of
from dbs.manager.middleware import current_ip

INVALID_CREDENTIALS: str = "That username and password don't match an account."
INACTIVE_ACCOUNT: str = "This account has been deactivated. Contact an administrator."


class Action:
    SIGN_IN = "auth.sign_in"
    SIGN_IN_FAILED = "auth.sign_in_failed"
    SIGN_OUT = "auth.sign_out"


class AccountService:
    def __init__(self, user: User | AnonymousUser | None = None) -> None:
        self.user: User | AnonymousUser | None = user
        self.users: UserRepository = UserRepository()

    def sign_in(self, request: Request, username: str, password: str) -> User:
        name_key = f"sign-in:name:{username.casefold()}"
        address_key = f"sign-in:address:{current_ip() or 'unknown'}"
        limits = (
            (name_key, settings.AUTH_FAILURES_PER_USER),
            (address_key, settings.AUTH_FAILURES_PER_ADDRESS),
        )
        if not throttle.counted(limits):
            throttle.given_back((name_key, address_key))
            self._refuse_sign_in(username, TooManyAttempts())

        user: User | None = authenticate(
            request=None, username=username, password=password
        )
        if user is None:
            refused = AuthenticationFailed(INVALID_CREDENTIALS)
            existing: User | None = self.users.find_by_username(username)
            if existing is not None and not existing.is_active:
                refused = AuthenticationFailed(INACTIVE_ACCOUNT)
            self._refuse_sign_in(username, refused)

        throttle.cleared((name_key,))
        throttle.given_back((address_key,))
        login(request, user)
        ActivityService(user).record(Action.SIGN_IN, target=user.get_username())
        return user

    def _refuse_sign_in(self, username: str, refused: Exception) -> NoReturn:
        ActivityService(None).record(
            Action.SIGN_IN_FAILED,
            target=username,
            status=audit.FAILED,
            error_code=error_code_of(refused),
        )
        raise refused

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

    def identity(self) -> dict[str, Any]:
        if not isinstance(self.user, User) or not self.user.is_authenticated:
            raise AuthenticationFailed(INVALID_CREDENTIALS)

        user: User = self.users.with_groups(self.user.pk) or self.user

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
        }

    def has_group(self, name: str) -> bool:
        if not isinstance(self.user, User) or not self.user.is_authenticated:
            return False
        if self.user.is_superuser:
            return True
        return self.users.in_group(self.user, name)
