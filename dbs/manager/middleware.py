from __future__ import annotations

import ipaddress
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar

_client_ip: ContextVar[str | None] = ContextVar("client_ip", default=None)


def current_ip() -> str | None:
    return _client_ip.get()


def client_ip(meta: Mapping[str, str]) -> str | None:
    raw = meta.get("REMOTE_ADDR", "") or ""
    try:
        address = ipaddress.ip_address(raw.strip())
    except ValueError:
        return None
    if getattr(address, "scope_id", None):
        return None
    return str(address)


@contextmanager
def request_origin(meta: Mapping[str, str]) -> Iterator[None]:
    token = _client_ip.set(client_ip(meta))
    try:
        yield
    finally:
        _client_ip.reset(token)


class RequestOriginMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        with request_origin(request.META):
            return self.get_response(request)
