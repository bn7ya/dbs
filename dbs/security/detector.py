from __future__ import annotations

from django.utils.module_loading import import_string

from ..conf import setting
from .baseline import base_calibration, base_model, calibrate, load_corpus
from .features import to_vector

MIN_PERSONAL_ROWS = 50

PERSONAL_ESTIMATORS = 80

_personal_cache = {}


TAIL_RISK = 0.80


def normalise(raw: float, calibration) -> float:
    middle, tail = calibration
    spread = middle - tail
    if spread <= 0:
        return 0.0
    return max(0.0, min(1.0, ((middle - raw) / spread) * TAIL_RISK))


class IsolationForestDetector:
    def score(self, user, values) -> float:
        vector = to_vector(values)
        scores = [
            normalise(base_model().score_samples([vector])[0], base_calibration())
        ]
        personal = self._personal(user)
        if personal is not None:
            forest, calibration = personal
            scores.append(normalise(forest.score_samples([vector])[0], calibration))
        return max(scores)

    def _personal(self, user):
        from ..models import SessionEvent

        rows = list(
            SessionEvent.objects.filter(user=user)
            .order_by("-created_at")
            .values_list("features", flat=True)[:2000]
        )
        vectors = [to_vector(row) for row in rows if isinstance(row, dict)]
        minimum = int(setting("DBS_ANOMALY_MIN_ROWS", MIN_PERSONAL_ROWS))
        if len(vectors) < minimum:
            return None
        cached = _personal_cache.get(user.pk)
        if cached is not None and cached[0] == len(vectors):
            return cached[1]
        from sklearn.ensemble import IsolationForest

        rows = vectors + _prior_sample(len(vectors))
        forest = IsolationForest(
            n_estimators=PERSONAL_ESTIMATORS, contamination=0.05, random_state=7
        )
        forest.fit(rows)
        fitted = (forest, calibrate(forest, rows))
        _personal_cache[user.pk] = (len(vectors), fitted)
        return fitted


def _prior_sample(personal_rows: int) -> list[list[float]]:
    rows = load_corpus()["rows"]
    share = max(0, min(len(rows), personal_rows * 4 - personal_rows))
    step = max(1, len(rows) // share) if share else 0
    return rows[::step][:share] if share else []


def forget(user_pk=None):
    if user_pk is None:
        _personal_cache.clear()
    else:
        _personal_cache.pop(user_pk, None)


def get_detector():
    path = setting("DBS_ANOMALY_DETECTOR", None)
    if path:
        return import_string(path)()
    return IsolationForestDetector()


RULES = (
    ("new_ip_prefix", 0.35, "this network is new for the account"),
    ("new_user_agent", 0.20, "this browser is new for the account"),
)


def rule_score(values) -> tuple[float, list[str]]:
    score = 0.0
    reasons = []
    for name, weight, message in RULES:
        if values.get(name):
            score += weight
            reasons.append(message)
    travel = values.get("travel_kmh", 0.0)
    if travel > 900:
        score += 0.6
        reasons.append(f"implies travelling at {travel:.0f} km/h since the last sighting")
    elif travel > 300:
        score += 0.25
        reasons.append(f"implies travelling at {travel:.0f} km/h since the last sighting")
    if values.get("action_risk", 0.0) >= 1.0 and values.get("new_ip_prefix"):
        score += 0.3
        reasons.append("a destructive action from an unrecognised network")
    return min(1.0, score), reasons

