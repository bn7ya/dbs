from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured


def setting(name: str, default):
    from django.conf import settings

    try:
        return getattr(settings, name, default)
    except ImproperlyConfigured:
        return default
