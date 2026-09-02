from __future__ import annotations

import hashlib
import ipaddress
import math
from datetime import timedelta

from django.utils import timezone

SCHEMA_VERSION = 1

FEATURE_NAMES = (
    "hour_sin",
    "hour_cos",
    "weekday",
    "seconds_since_previous",
    "events_last_five_minutes",
    "action_risk",
    "session_age_minutes",
    "recent_failures",
    "new_ip_prefix",
    "new_user_agent",
    "distinct_prefixes_today",
    "distance_km",
    "travel_kmh",
)

ACTION_RISK = {
    "view": 0.1,
    "backup": 0.5,
    "download": 0.7,
    "console": 0.8,
    "target_write": 0.8,
    "restore": 1.0,
    "delete": 1.0,
}

EARTH_RADIUS_KM = 6371.0


def action_risk(name: str) -> float:
    return ACTION_RISK.get(name, ACTION_RISK["view"])


def ip_prefix(address: str) -> str:
    if not address:
        return ""
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return ""
    network = 24 if parsed.version == 4 else 48
    return str(ipaddress.ip_network(f"{parsed}/{network}", strict=False))


def digest(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8", "replace")).hexdigest()


def haversine_km(first, second) -> float:
    lat1, lon1 = math.radians(first[0]), math.radians(first[1])
    lat2, lon2 = math.radians(second[0]), math.radians(second[1])
    delta = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(
        (lon2 - lon1) / 2
    ) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(delta)))


def to_vector(values: dict) -> list[float]:
    return [float(values.get(name, 0.0)) for name in FEATURE_NAMES]


def build(observation) -> dict:
    moment = observation.moment or timezone.now()
    angle = 2 * math.pi * (moment.hour + moment.minute / 60.0) / 24.0
    return {
        "hour_sin": math.sin(angle),
        "hour_cos": math.cos(angle),
        "weekday": float(moment.weekday()),
        "seconds_since_previous": _capped(observation.seconds_since_previous, 86400),
        "events_last_five_minutes": _capped(observation.events_last_five_minutes, 500),
        "action_risk": action_risk(observation.action),
        "session_age_minutes": _capped(observation.session_age_minutes, 10080),
        "recent_failures": _capped(observation.recent_failures, 50),
        "new_ip_prefix": 1.0 if observation.new_ip_prefix else 0.0,
        "new_user_agent": 1.0 if observation.new_user_agent else 0.0,
        "distinct_prefixes_today": _capped(observation.distinct_prefixes_today, 50),
        "distance_km": _capped(observation.distance_km, 20000),
        "travel_kmh": _capped(observation.travel_kmh, 5000),
    }


def _capped(value, ceiling) -> float:
    if value is None:
        return 0.0
    return float(max(0.0, min(float(value), float(ceiling))))


class Observation:
    def __init__(self, **values):
        self.moment = values.get("moment")
        self.action = values.get("action", "view")
        self.seconds_since_previous = values.get("seconds_since_previous", 0.0)
        self.events_last_five_minutes = values.get("events_last_five_minutes", 0.0)
        self.session_age_minutes = values.get("session_age_minutes", 0.0)
        self.recent_failures = values.get("recent_failures", 0.0)
        self.new_ip_prefix = values.get("new_ip_prefix", False)
        self.new_user_agent = values.get("new_user_agent", False)
        self.distinct_prefixes_today = values.get("distinct_prefixes_today", 1.0)
        self.distance_km = values.get("distance_km", 0.0)
        self.travel_kmh = values.get("travel_kmh", 0.0)


def observe_request(user, request, action, location=None):
    from ..models import KnownLocation, SessionEvent

    now = timezone.now()
    address = client_address(request)
    prefix = ip_prefix(address)
    agent = digest(request.META.get("HTTP_USER_AGENT", ""))
    recent = list(
        SessionEvent.objects.filter(user=user).order_by("-created_at")[:200]
    )
    previous = recent[0] if recent else None
    seen_prefixes = {event.ip_prefix for event in recent if event.ip_prefix}
    seen_agents = {event.ua_hash for event in recent if event.ua_hash}
    day_start = now - timedelta(days=1)
    today = {
        event.ip_prefix
        for event in recent
        if event.ip_prefix and event.created_at >= day_start
    }
    window = now - timedelta(minutes=5)
    distance, speed = _travel(user, recent, location, now, KnownLocation)

    observation = Observation(
        moment=now,
        action=action,
        seconds_since_previous=(
            (now - previous.created_at).total_seconds() if previous else 0.0
        ),
        events_last_five_minutes=sum(
            1 for event in recent if event.created_at >= window
        ),
        session_age_minutes=_session_age_minutes(request, now),
        recent_failures=0.0,
        new_ip_prefix=bool(prefix) and prefix not in seen_prefixes,
        new_user_agent=bool(agent) and agent not in seen_agents,
        distinct_prefixes_today=len(today) or 1,
        distance_km=distance,
        travel_kmh=speed,
    )
    return observation, address, prefix, agent


def _travel(user, recent, location, now, KnownLocation):
    if not location:
        return 0.0, 0.0
    here = (location["latitude"], location["longitude"])
    known = list(KnownLocation.objects.filter(user=user))
    distance = 0.0
    if known:
        nearest = min(
            haversine_km(here, (place.latitude, place.longitude)) for place in known
        )
        allowance = min(place.radius_km for place in known)
        distance = max(0.0, nearest - allowance)
    speed = 0.0
    for event in recent:
        if event.latitude is None or event.longitude is None:
            continue
        elapsed = (now - event.created_at).total_seconds() / 3600.0
        if elapsed <= 0:
            break
        speed = haversine_km(here, (event.latitude, event.longitude)) / elapsed
        break
    return distance, speed


def _session_age_minutes(request, now):
    session = getattr(request, "session", None)
    started = session.get("dbs_session_started") if session is not None else None
    if not started:
        return 0.0
    from django.utils.dateparse import parse_datetime

    parsed = parse_datetime(started)
    if parsed is None:
        return 0.0
    return max(0.0, (now - parsed).total_seconds() / 60.0)


def client_address(request) -> str:
    from ..conf import setting

    if setting("DBS_TRUST_FORWARDED_FOR", False):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or ""
