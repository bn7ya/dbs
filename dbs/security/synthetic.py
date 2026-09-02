from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from . import features

BASE_DAY = datetime(2026, 3, 2, tzinfo=timezone.utc)

ARCHETYPES = ("office", "night_owl", "weekend", "two_devices", "traveller")

ATTACKS = (
    "impossible_travel",
    "night_burst",
    "destructive_spree",
    "agent_switch",
)


def _moment(rng, day_offset, hour_low, hour_high):
    hour = rng.uniform(hour_low, hour_high) % 24
    return BASE_DAY + timedelta(
        days=day_offset, hours=hour, minutes=rng.uniform(0, 59)
    )


def _observation(**values):
    return features.build(features.Observation(**values))


def _office(rng, day):
    return _observation(
        moment=_moment(rng, day * 1 + rng.randint(0, 4), 8, 18),
        action=rng.choice(["view", "view", "view", "backup", "download"]),
        seconds_since_previous=rng.expovariate(1 / 240.0),
        events_last_five_minutes=rng.randint(1, 14),
        session_age_minutes=rng.uniform(0, 240),
        distinct_prefixes_today=1,
    )


def _night_owl(rng, day):
    return _observation(
        moment=_moment(rng, day, 20, 26),
        action=rng.choice(["view", "view", "backup"]),
        seconds_since_previous=rng.expovariate(1 / 300.0),
        events_last_five_minutes=rng.randint(1, 10),
        session_age_minutes=rng.uniform(0, 180),
        distinct_prefixes_today=1,
    )


def _weekend(rng, day):
    return _observation(
        moment=_moment(rng, day, 10, 20) + timedelta(days=(5 - day % 7) % 7),
        action=rng.choice(["view", "view", "backup", "restore"]),
        seconds_since_previous=rng.expovariate(1 / 400.0),
        events_last_five_minutes=rng.randint(1, 8),
        session_age_minutes=rng.uniform(0, 120),
        distinct_prefixes_today=1,
    )


def _two_devices(rng, day):
    first_sighting = rng.random() < 0.08
    return _observation(
        moment=_moment(rng, day, 7, 22),
        action=rng.choice(["view", "view", "backup", "console"]),
        seconds_since_previous=rng.expovariate(1 / 200.0),
        events_last_five_minutes=rng.randint(1, 16),
        session_age_minutes=rng.uniform(0, 300),
        new_user_agent=first_sighting,
        distinct_prefixes_today=2,
    )


def _traveller(rng, day):
    moving = rng.random() < 0.25
    return _observation(
        moment=_moment(rng, day, 6, 23),
        action=rng.choice(["view", "view", "backup", "download"]),
        seconds_since_previous=rng.expovariate(1 / 600.0),
        events_last_five_minutes=rng.randint(1, 9),
        session_age_minutes=rng.uniform(0, 200),
        new_ip_prefix=moving and rng.random() < 0.5,
        distinct_prefixes_today=rng.randint(1, 3),
        distance_km=rng.uniform(0, 300) if moving else 0.0,
        travel_kmh=rng.uniform(0, 90) if moving else 0.0,
    )


GENERATORS = {
    "office": _office,
    "night_owl": _night_owl,
    "weekend": _weekend,
    "two_devices": _two_devices,
    "traveller": _traveller,
}

WEIGHTS = (0.45, 0.15, 0.10, 0.18, 0.12)


def normal_rows(count: int = 4000, seed: int = 20260302) -> list[list[float]]:
    rng = random.Random(seed)
    rows = []
    for index in range(count):
        archetype = rng.choices(ARCHETYPES, weights=WEIGHTS, k=1)[0]
        rows.append(features.to_vector(GENERATORS[archetype](rng, index % 90)))
    return rows


def attack_rows(count: int = 60, seed: int = 7717) -> dict[str, list[list[float]]]:
    rng = random.Random(seed)
    built = {name: [] for name in ATTACKS}
    for index in range(count):
        day = index % 90
        built["impossible_travel"].append(
            features.to_vector(
                _observation(
                    moment=_moment(rng, day, 0, 24),
                    action="view",
                    seconds_since_previous=rng.uniform(300, 1800),
                    events_last_five_minutes=rng.randint(1, 6),
                    session_age_minutes=rng.uniform(0, 60),
                    new_ip_prefix=True,
                    distinct_prefixes_today=rng.randint(2, 4),
                    distance_km=rng.uniform(1500, 9000),
                    travel_kmh=rng.uniform(1200, 4000),
                )
            )
        )
        built["night_burst"].append(
            features.to_vector(
                _observation(
                    moment=_moment(rng, day, 2, 5),
                    action=rng.choice(["download", "console", "restore"]),
                    seconds_since_previous=rng.uniform(0.5, 5),
                    events_last_five_minutes=rng.randint(60, 200),
                    session_age_minutes=rng.uniform(0, 10),
                    new_ip_prefix=True,
                    new_user_agent=True,
                    distinct_prefixes_today=rng.randint(4, 9),
                )
            )
        )
        built["destructive_spree"].append(
            features.to_vector(
                _observation(
                    moment=_moment(rng, day, 0, 24),
                    action="delete",
                    seconds_since_previous=rng.uniform(0.2, 3),
                    events_last_five_minutes=rng.randint(30, 90),
                    session_age_minutes=rng.uniform(0, 20),
                    new_ip_prefix=rng.random() < 0.6,
                    distinct_prefixes_today=rng.randint(2, 5),
                )
            )
        )
        built["agent_switch"].append(
            features.to_vector(
                _observation(
                    moment=_moment(rng, day, 0, 24),
                    action=rng.choice(["restore", "console", "download"]),
                    seconds_since_previous=rng.uniform(1, 30),
                    events_last_five_minutes=rng.randint(10, 40),
                    session_age_minutes=rng.uniform(300, 5000),
                    new_ip_prefix=True,
                    new_user_agent=True,
                    distinct_prefixes_today=rng.randint(3, 7),
                )
            )
        )
    return built


def typical_row() -> list[float]:
    rng = random.Random(11)
    return features.to_vector(_office(rng, 3))
