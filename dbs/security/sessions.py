from __future__ import annotations

from importlib import import_module

from django.conf import settings
from django.contrib.auth import SESSION_KEY

from .. import transactions

REAUTH_FLAG = "dbs_must_reauthenticate"

LAST_ACTIVE = "dbs_last_active"

ACTIVITY_RESOLUTION_SECONDS = 60


def _store():
    return import_module(settings.SESSION_ENGINE).SessionStore


def terminate(user) -> int:
    from django.contrib.sessions.models import Session
    from django.utils import timezone

    if settings.SESSION_ENGINE != "django.contrib.sessions.backends.db":
        return 0
    with transactions.reading_for(Session):
        keys = [
            session.pk
            for session in Session.objects.filter(expire_date__gte=timezone.now())
            if str(session.get_decoded().get(SESSION_KEY)) == str(user.pk)
        ]
    if not keys:
        return 0
    with transactions.atomic_for(Session):
        ended, _ = Session.objects.filter(pk__in=keys).delete()
    return ended


def mark_for_reauthentication(request) -> None:
    session = getattr(request, "session", None)
    if session is not None:
        session[REAUTH_FLAG] = True


def clear_reauthentication(request) -> None:
    session = getattr(request, "session", None)
    if session is not None:
        session.pop(REAUTH_FLAG, None)


def must_reauthenticate(request) -> bool:
    session = getattr(request, "session", None)
    return bool(session is not None and session.get(REAUTH_FLAG))


def _last_active(session):
    value = session.get(LAST_ACTIVE)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def idle_expired(request, minutes, now) -> bool:
    session = getattr(request, "session", None)
    if not minutes or session is None:
        return False
    last = _last_active(session)
    return last is not None and now - last > minutes * 60


def mark_active(request, now) -> None:
    session = getattr(request, "session", None)
    if session is None:
        return
    last = _last_active(session)
    if last is None or now - last >= ACTIVITY_RESOLUTION_SECONDS:
        session[LAST_ACTIVE] = int(now)
