from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from ..conf import setting

DEFAULT_RETENTION_DAYS = 90

SESSION_COUNT = "session_count"


def retention_days() -> int:
    return int(setting("DBS_SECURITY_RETENTION_DAYS", DEFAULT_RETENTION_DAYS))


def requests_for(user):
    from ..models import SessionEvent

    return SessionEvent.objects.filter(user=user).exclude(kind=SESSION_COUNT)


def recorded_requests():
    from ..models import SessionEvent

    return SessionEvent.objects.exclude(kind=SESSION_COUNT)


def sessions_seen(user) -> int:
    from ..models import SessionEvent

    live = requests_for(user).values("session_key_hash").distinct().count()
    counter = (
        SessionEvent.objects.filter(user=user, kind=SESSION_COUNT)
        .values_list("features", flat=True)
        .first()
    )
    return live + _counted(counter)


def _counted(features) -> int:
    if not isinstance(features, dict):
        return 0
    try:
        return max(0, int(features.get("sessions", 0)))
    except (TypeError, ValueError):
        return 0


def purge(days=None):
    from ..models import AnomalyEvent

    days = retention_days() if days is None else int(days)
    cutoff = timezone.now() - timedelta(days=days)
    with transaction.atomic():
        _carry_session_counts(cutoff)
        events, _ = recorded_requests().filter(created_at__lt=cutoff).delete()
        anomalies, _ = AnomalyEvent.objects.filter(created_at__lt=cutoff).delete()
    return events, anomalies


def _carry_session_counts(cutoff):
    expiring = recorded_requests().filter(created_at__lt=cutoff)
    for user_id in set(expiring.order_by().values_list("user_id", flat=True).distinct()):
        ending = _session_hashes(expiring.filter(user_id=user_id))
        continuing = _session_hashes(
            recorded_requests().filter(user_id=user_id, created_at__gte=cutoff)
        )
        ended = len(ending - continuing)
        if ended:
            _add_sessions(user_id, ended)


def _session_hashes(queryset):
    return set(queryset.order_by().values_list("session_key_hash", flat=True).distinct())


def _add_sessions(user_id, count):
    from ..models import SessionEvent

    counter = SessionEvent.objects.filter(user_id=user_id, kind=SESSION_COUNT).first()
    if counter is None:
        SessionEvent.objects.create(
            user_id=user_id, kind=SESSION_COUNT, features={"sessions": count}
        )
        return
    counter.features = {"sessions": _counted(counter.features) + count}
    counter.save(update_fields=["features"])
