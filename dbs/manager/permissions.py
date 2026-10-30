from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from typing import Any, TypeVar, cast

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.exceptions import APIException

Method = TypeVar("Method", bound=Callable[..., Any])


class Role:
    MASTER = "master"
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"

    CHOICES = (
        (MASTER, "Master"),
        (ADMIN, "Admin"),
        (OPERATOR, "Operator"),
        (VIEWER, "Viewer"),
    )
    RANKS = {VIEWER: 1, OPERATOR: 2, ADMIN: 3, MASTER: 4}
    ASSIGNABLE = (ADMIN, OPERATOR, VIEWER)
    NAMED = {
        MASTER: "the master account",
        ADMIN: "an admin",
        OPERATOR: "an operator",
        VIEWER: "a viewer",
    }


class Capability:
    ACCOUNTS_MANAGE = "accounts.manage"
    SERVERS_MANAGE = "servers.manage"
    SERVERS_CHECK = "servers.check"
    APPLICATIONS_MANAGE = "applications.manage"
    APPLICATIONS_CHECK = "applications.check"
    APPLICATIONS_PASSPHRASE = "applications.passphrase"
    BACKUPS_TAKE = "backups.take"
    BACKUPS_VERIFY = "backups.verify"
    BACKUPS_DOWNLOAD = "backups.download"
    BACKUPS_UPLOAD = "backups.upload"
    BACKUPS_DELETE = "backups.delete"
    BACKUPS_REHEARSE = "backups.rehearse"
    BACKUPS_RESTORE = "backups.restore"
    PLANS_MANAGE = "plans.manage"
    PLANS_RUN = "plans.run"
    ENV_PULL = "env.pull"
    ENV_REVEAL = "env.reveal"
    ENV_PUSH = "env.push"
    FILES_DOWNLOAD = "files.download"
    FILES_CHANGE = "files.change"
    REDEPLOY_REHEARSE = "redeploy.rehearse"
    REDEPLOY_RUN = "redeploy.run"
    RELOCATION_REHEARSE = "relocation.rehearse"
    RELOCATION_RUN = "relocation.run"
    SHELL_OPEN = "shell.open"
    CONSOLE_RUN = "console.run"


MINIMUM_ROLE = {
    Capability.ACCOUNTS_MANAGE: Role.MASTER,
    Capability.SERVERS_MANAGE: Role.ADMIN,
    Capability.SERVERS_CHECK: Role.OPERATOR,
    Capability.APPLICATIONS_MANAGE: Role.ADMIN,
    Capability.APPLICATIONS_CHECK: Role.OPERATOR,
    Capability.APPLICATIONS_PASSPHRASE: Role.ADMIN,
    Capability.BACKUPS_TAKE: Role.OPERATOR,
    Capability.BACKUPS_VERIFY: Role.OPERATOR,
    Capability.BACKUPS_DOWNLOAD: Role.OPERATOR,
    Capability.BACKUPS_UPLOAD: Role.ADMIN,
    Capability.BACKUPS_DELETE: Role.ADMIN,
    Capability.BACKUPS_REHEARSE: Role.OPERATOR,
    Capability.BACKUPS_RESTORE: Role.ADMIN,
    Capability.PLANS_MANAGE: Role.ADMIN,
    Capability.PLANS_RUN: Role.OPERATOR,
    Capability.ENV_PULL: Role.OPERATOR,
    Capability.ENV_REVEAL: Role.ADMIN,
    Capability.ENV_PUSH: Role.ADMIN,
    Capability.FILES_DOWNLOAD: Role.OPERATOR,
    Capability.FILES_CHANGE: Role.ADMIN,
    Capability.REDEPLOY_REHEARSE: Role.OPERATOR,
    Capability.REDEPLOY_RUN: Role.ADMIN,
    Capability.RELOCATION_REHEARSE: Role.OPERATOR,
    Capability.RELOCATION_RUN: Role.ADMIN,
    Capability.SHELL_OPEN: Role.ADMIN,
    Capability.CONSOLE_RUN: Role.VIEWER,
}

REHEARSALS = {
    Capability.BACKUPS_RESTORE: ("rehearse", Capability.BACKUPS_REHEARSE),
    Capability.REDEPLOY_RUN: ("rehearsal", Capability.REDEPLOY_REHEARSE),
    Capability.RELOCATION_RUN: ("rehearsal", Capability.RELOCATION_REHEARSE),
}


class RoleRequired(APIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_code = "role_required"
    default_detail = "Your account's role does not allow this."

    def __init__(self, needed: str, held: str | None) -> None:
        self.role = needed
        super().__init__(refusal(needed, held))


def refusal(needed: str, held: str | None) -> str:
    if needed == Role.MASTER:
        wanted = "Only the master account can do this"
    else:
        wanted = f"This needs the {needed} role or higher"
    return f"{wanted}; your account is {Role.NAMED.get(held, 'without a role')}."


def role_of(user: Any) -> str | None:
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    found = (
        get_user_model()
        .objects.filter(pk=user.pk, is_active=True)
        .values_list("pk", "manager_account__role")
        .first()
    )
    if found is None:
        return None
    return found[1] or Role.VIEWER


def allows(role: str | None, capability: str) -> bool:
    return Role.RANKS.get(role or "", 0) >= Role.RANKS[MINIMUM_ROLE[capability]]


def capabilities(role: str | None) -> list[str]:
    return sorted(name for name in MINIMUM_ROLE if allows(role, name))


def can(user: Any, capability: str) -> bool:
    return user is None or allows(role_of(user), capability)


def require(user: Any, capability: str) -> None:
    if user is None:
        return
    role = role_of(user)
    if not allows(role, capability):
        raise RoleRequired(MINIMUM_ROLE[capability], role)


def requires(capability: str) -> Callable[[Method], Method]:
    def decorate(method: Method) -> Method:
        signature = inspect.signature(method)
        flag, rehearsal = REHEARSALS.get(capability, (None, None))

        @functools.wraps(method)
        def checked(service: Any, *args: Any, **kwargs: Any) -> Any:
            needed = capability
            if flag is not None:
                bound = signature.bind(service, *args, **kwargs)
                bound.apply_defaults()
                if bound.arguments.get(flag):
                    needed = rehearsal
            require(service.user, needed)
            return method(service, *args, **kwargs)

        return cast(Method, checked)

    return decorate
