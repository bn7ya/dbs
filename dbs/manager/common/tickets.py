from __future__ import annotations

import re
import secrets
from typing import Any

from django.core.cache import cache

PREFIX = "download-ticket:"
LIFETIME_SECONDS = 60
TOKEN_BYTES = 32
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")


def issue(user: Any, subject: str) -> str:
    token = secrets.token_urlsafe(TOKEN_BYTES)
    cache.set(PREFIX + token, _holder(user, subject), timeout=LIFETIME_SECONDS)
    return token


def redeem(token: str, user: Any, subject: str) -> bool:
    if not TOKEN.fullmatch(token):
        return False
    key = PREFIX + token
    if cache.get(key) != _holder(user, subject):
        return False
    return bool(cache.delete(key))


def _holder(user: Any, subject: str) -> dict[str, str]:
    return {"user": str(getattr(user, "pk", "")), "subject": subject}
