from __future__ import annotations

import ipaddress
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings
from django.http import JsonResponse

_client_ip: ContextVar[str | None] = ContextVar("client_ip", default=None)

FORWARDED_SCHEMES = ("http", "https")
OPEN_WHILE_PASSWORD_EXPIRED = frozenset(
    {
        "accounts:csrf",
        "accounts:login",
        "accounts:two-factor",
        "accounts:enrollment",
        "accounts:enrollment-confirm",
        "accounts:logout",
        "accounts:me",
        "accounts:password",
        "health",
        "setup",
    }
)


def current_ip() -> str | None:
    return _client_ip.get()


def parsed_address(raw: str):
    try:
        address = ipaddress.ip_address(raw.strip())
    except ValueError:
        return None
    if getattr(address, "scope_id", None):
        return None
    return address


def client_ip(meta: Mapping[str, str]) -> str | None:
    address = parsed_address(meta.get("REMOTE_ADDR", "") or "")
    return None if address is None else str(address)


def trusted_networks(text: str) -> list:
    networks = []
    for part in text.split(","):
        if part.strip():
            networks.append(ipaddress.ip_network(part.strip(), strict=False))
    return networks


def trusted(address, networks: Sequence) -> bool:
    return address is not None and any(
        address.version == network.version and address in network
        for network in networks
    )


def forwarded_client(header: str, networks: Sequence) -> str | None:
    hops = [parsed_address(hop) for hop in header.split(",") if hop.strip()]
    for hop in reversed(hops):
        if hop is None:
            return None
        if not trusted(hop, networks):
            return str(hop)
    return None


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


class TrustedProxyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        networks = getattr(settings, "DBS_MANAGER_TRUSTED_PROXIES", [])
        peer = parsed_address(request.META.get("REMOTE_ADDR", "") or "")
        if networks and trusted(peer, networks):
            self._forwarded(request, networks)
        response = self.get_response(request)
        if request.is_secure():
            for name in (settings.SESSION_COOKIE_NAME, settings.CSRF_COOKIE_NAME):
                if name in response.cookies:
                    response.cookies[name]["secure"] = True
                    response.cookies[name]["httponly"] = True
        return response

    def _forwarded(self, request, networks: Sequence) -> None:
        scheme = request.META.get("HTTP_X_FORWARDED_PROTO", "").split(",")[0]
        if scheme.strip().lower() in FORWARDED_SCHEMES:
            request.META["wsgi.url_scheme"] = scheme.strip().lower()
        client = forwarded_client(
            request.META.get("HTTP_X_FORWARDED_FOR", ""), networks
        )
        if client is not None:
            request.META["DBS_MANAGER_PROXY_ADDR"] = request.META.get("REMOTE_ADDR", "")
            request.META["REMOTE_ADDR"] = client


class PasswordAgeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view, args, kwargs):
        match = request.resolver_match
        if (
            not request.path.startswith("/api/")
            or match is None
            or match.view_name in OPEN_WHILE_PASSWORD_EXPIRED
            or not request.user.is_authenticated
        ):
            return None
        from dbs.manager.accounts.exceptions import PasswordChangeRequired
        from dbs.manager.accounts.services import AccountService

        if not AccountService(request.user).password_change_required():
            return None
        refused = PasswordChangeRequired()
        return JsonResponse(
            {"error": {"code": refused.default_code, "message": str(refused.detail)}},
            status=refused.status_code,
        )
