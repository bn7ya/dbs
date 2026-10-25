from __future__ import annotations

from django.core import checks
from django.utils.module_loading import import_string

from .. import extras
from ..conf import setting

GUARD_MIDDLEWARE = "dbs.security.middleware.DBSSecurityMiddleware"

AUTH_MIDDLEWARE = "django.contrib.auth.middleware.AuthenticationMiddleware"

REPAIR = extras.reinstall_command()


def _middleware():
    return [str(entry) for entry in (setting("MIDDLEWARE", ()) or ())]


def guard_installed() -> bool:
    return GUARD_MIDDLEWARE in _middleware()


def _authenticates(path) -> bool:
    if path == AUTH_MIDDLEWARE:
        return True
    try:
        candidate = import_string(path)
    except ImportError:
        return False
    from django.contrib.auth.middleware import AuthenticationMiddleware

    return isinstance(candidate, type) and issubclass(candidate, AuthenticationMiddleware)


def runs_before_authentication() -> bool:
    stack = _middleware()
    if GUARD_MIDDLEWARE not in stack:
        return False
    position = stack.index(GUARD_MIDDLEWARE)
    return not any(_authenticates(path) for path in stack[:position])


def forwarded_for_unanchored() -> bool:
    from .features import trusted_proxies

    return bool(setting("DBS_TRUST_FORWARDED_FOR", False)) and not trusted_proxies()


NETWORK_SETTINGS = ("DBS_TRUSTED_PROXIES", "DBS_TRUSTED_NETWORKS")


def ignored_network_settings() -> dict:
    from .networks import ignored_networks

    found = {}
    for name in NETWORK_SETTINGS:
        ignored = ignored_networks(setting(name, ()) or ())
        if ignored:
            found[name] = ignored
    return found


def scoring_model_missing() -> bool:
    from .detector import model_available

    return guard_installed() and not model_available()


@checks.register(checks.Tags.security)
def check_session_guard(app_configs=None, **kwargs):
    found = []
    if forwarded_for_unanchored():
        found.append(
            checks.Warning(
                "DBS_TRUST_FORWARDED_FOR is on but DBS_TRUSTED_PROXIES names no proxy "
                "network, so the session guard ignores X-Forwarded-For and scores the "
                "direct peer address.",
                hint='List your proxies, for example DBS_TRUSTED_PROXIES = ["10.0.0.0/24"].',
                id="dbs.security.W001",
            )
        )
    if runs_before_authentication():
        found.append(
            checks.Warning(
                "DBSSecurityMiddleware runs before AuthenticationMiddleware, so it never "
                "sees a signed-in user and the session guard scores nothing.",
                hint=f'Move "{GUARD_MIDDLEWARE}" below "{AUTH_MIDDLEWARE}" in MIDDLEWARE.',
                id="dbs.security.W002",
            )
        )
    if scoring_model_missing():
        found.append(
            checks.Warning(
                "scikit-learn cannot be imported, so the session guard scores with its rules "
                "alone and the anomaly model is off.",
                hint=REPAIR,
                id="dbs.security.W003",
            )
        )
    for name, ignored in ignored_network_settings().items():
        found.append(
            checks.Warning(
                f"{name} lists {', '.join(repr(entry) for entry in ignored)}, which the "
                "session guard ignores: each entry must be a network no broader than /8 "
                "for IPv4 or /16 for IPv6.",
                hint=f'Write one network per entry, for example {name} = ["10.0.0.0/24"].',
                id="dbs.security.W004",
            )
        )
    return found
