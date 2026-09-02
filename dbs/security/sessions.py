from __future__ import annotations

from importlib import import_module

from django.conf import settings
from django.contrib.auth import SESSION_KEY

REAUTH_FLAG = "dbs_must_reauthenticate"


def _store():
    return import_module(settings.SESSION_ENGINE).SessionStore


def terminate(user) -> int:
    from django.contrib.sessions.models import Session
    from django.utils import timezone

    ended = 0
    if settings.SESSION_ENGINE == "django.contrib.sessions.backends.db":
        for session in Session.objects.filter(expire_date__gte=timezone.now()):
            if str(session.get_decoded().get(SESSION_KEY)) == str(user.pk):
                session.delete()
                ended += 1
        return ended
    return ended


def mark_for_reauthentication(request) -> None:
    session = getattr(request, "session", None)
    if session is not None:
        session[REAUTH_FLAG] = True


def clear_reauthentication(request) -> None:
    session = getattr(request, "session", None)
    if session is not None:
        session.pop(REAUTH_FLAG, None)
