from __future__ import annotations

from ..conf import setting

COORDINATE_PRECISION = 2

MAX_ACCURACY_M = 200000


def enabled() -> bool:
    return bool(setting("DBS_GEOLOCATION", False))


def clean(payload) -> dict | None:
    if not enabled() or not isinstance(payload, dict):
        return None
    try:
        latitude = float(payload["latitude"])
        longitude = float(payload["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (-90.0 <= latitude <= 90.0) or not (-180.0 <= longitude <= 180.0):
        return None
    accuracy = payload.get("accuracy")
    try:
        accuracy = float(accuracy) if accuracy is not None else None
    except (TypeError, ValueError):
        accuracy = None
    if accuracy is not None and (accuracy < 0 or accuracy > MAX_ACCURACY_M):
        accuracy = None
    return {
        "latitude": round(latitude, COORDINATE_PRECISION),
        "longitude": round(longitude, COORDINATE_PRECISION),
        "accuracy": accuracy,
    }
