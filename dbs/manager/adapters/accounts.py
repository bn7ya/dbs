from __future__ import annotations

import sys
from typing import Any

from django.contrib.auth import get_user_model

from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.accounts.services import AccountService
from dbs.manager.adapters import AdapterError


def acting(name: str | None) -> Any:
    if name:
        user = UserRepository().find_by_username(name)
        if user is None or not user.is_active:
            raise AdapterError(f"there is no account named {name!r}.")
        return user
    active = list(get_user_model().objects.filter(is_active=True).order_by("username"))
    if not active:
        raise AdapterError(
            "the manager has no account yet. Add one with: django_dbs createuser NAME"
        )
    if len(active) > 1:
        names = ", ".join(user.get_username() for user in active)
        raise AdapterError(f"pick the account to act as with --as NAME ({names}).")
    return active[0]


def expiry_warning(user: Any) -> str:
    if not AccountService(user).password_change_required():
        return ""
    name = user.get_username()
    return (
        f"Warning: the password of {name} has expired. Change it in the manager, or "
        f"with: django_dbs password {name}"
    )


def with_expiry_warning(text: str, user: Any) -> str:
    return " ".join(part for part in (text, expiry_warning(user)) if part)


def warn_if_expired(user: Any) -> None:
    warning = expiry_warning(user)
    if warning:
        print(warning, file=sys.stderr)
