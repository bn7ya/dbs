from __future__ import annotations

from django.core import checks

from ..conf import setting


def forwarded_for_unanchored() -> bool:
    from .features import trusted_proxies

    return bool(setting("DBS_TRUST_FORWARDED_FOR", False)) and not trusted_proxies()


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
    return found
