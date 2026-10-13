from __future__ import annotations

import sys
from typing import Any

from rest_framework.exceptions import APIException, ValidationError

from dbs import __version__
from dbs.manager.adapters import AdapterError, accounts
from dbs.manager.adapters.problems import problem
from dbs.manager.mcp import tools
from dbs.manager.mcp.protocol import Server

NAME = "django-dbs"
ACCOUNT_PASSWORD = "account_password"
NEEDS_PASSWORD = (
    "This needs your account password, which Claude never takes. Do it in the manager's "
    "interface, or in a terminal with the same django_dbs command and --password-stdin."
)


def describe(exc: BaseException) -> str | None:
    if isinstance(exc, ValidationError) and _asks_for_password(exc.detail):
        return NEEDS_PASSWORD
    if isinstance(exc, APIException):
        return problem(exc)
    if isinstance(exc, AdapterError):
        return str(exc)
    return None


def build(user: Any) -> Server:
    return Server(
        tools.build(user),
        name=NAME,
        version=__version__,
        instructions=accounts.with_expiry_warning(tools.INSTRUCTIONS, user),
        describe=describe,
    )


def serve(session: Any) -> int:
    build(session.user).serve(sys.stdin, sys.stdout)
    return 0


def _asks_for_password(detail: Any) -> bool:
    return isinstance(detail, dict) and ACCOUNT_PASSWORD in detail
