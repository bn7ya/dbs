from __future__ import annotations

import importlib
import logging
import threading
import time
from dataclasses import dataclass

from django.utils.module_loading import import_string

from ..conf import setting
from .baseline import base_calibration, base_model, calibrate, load_corpus
from .features import to_vector
from .telemetry import requests_for

logger = logging.getLogger("dbs")

MIN_PERSONAL_ROWS = 50

PERSONAL_ESTIMATORS = 80

WINDOW_ROWS = 2000

REFIT_SECONDS = 15 * 60

REFIT_EVENTS = 200

TAIL_RISK = 0.80

_lock = threading.Lock()

_fits = {}

_refitting = set()

_generation = 0


@dataclass
class PersonalFit:
    model: tuple | None
    newest_id: int | None
    rows: int
    fitted_at: float
    scored: int = 0


def model_available() -> bool:
    try:
        importlib.import_module("sklearn.ensemble")
    except ImportError:
        return False
    return True


def normalise(raw: float, calibration) -> float:
    middle, tail = calibration
    spread = middle - tail
    if spread <= 0:
        return 0.0
    return max(0.0, min(1.0, ((middle - raw) / spread) * TAIL_RISK))


class IsolationForestDetector:
    def score(self, user, values) -> float:
        if not model_available():
            return 0.0
        vector = to_vector(values)
        scores = [
            normalise(base_model().score_samples([vector])[0], base_calibration())
        ]
        fitted = personal_model(user)
        if fitted is not None:
            forest, calibration = fitted
            scores.append(normalise(forest.score_samples([vector])[0], calibration))
        return max(scores)


def model_score(user, values, *, learning=False) -> float:
    engine = get_detector()
    if learning and isinstance(engine, IsolationForestDetector):
        return 0.0
    return engine.score(user, values)


def minimum_rows() -> int:
    return int(setting("DBS_ANOMALY_MIN_ROWS", MIN_PERSONAL_ROWS))


def _clock() -> float:
    return time.monotonic()


def personal_model(user):
    newest = (
        requests_for(user).order_by("-created_at").values_list("id", flat=True).first()
    )
    with _lock:
        fit = _fits.get(user.pk)
        if fit is not None:
            fit.scored += 1
        due = _due(fit, newest)
    if due and _ready_to_fit(user, fit, newest):
        request_refit(user.pk)
    return fit.model if fit is not None else None


def _due(fit, newest) -> bool:
    if newest is None:
        return False
    if fit is None:
        return True
    if newest == fit.newest_id:
        return False
    if _clock() - fit.fitted_at >= REFIT_SECONDS:
        return True
    if fit.model is None:
        return fit.rows + fit.scored >= minimum_rows()
    return fit.scored >= REFIT_EVENTS


def _ready_to_fit(user, fit, newest) -> bool:
    if fit is not None and fit.model is not None:
        return True
    rows = requests_for(user).count()
    if rows >= minimum_rows():
        return True
    with _lock:
        _fits[user.pk] = PersonalFit(None, newest, rows, _clock())
    return False


def request_refit(user_pk) -> bool:
    with _lock:
        if user_pk in _refitting:
            return False
        _refitting.add(user_pk)
        generation = _generation
    try:
        start_refit(user_pk, generation)
    except Exception:
        with _lock:
            _refitting.discard(user_pk)
        logger.warning("could not start the DBS guard refit", exc_info=True)
        return False
    return True


def start_refit(user_pk, generation) -> None:
    threading.Thread(
        target=_refit_in_background,
        args=(user_pk, generation),
        name="dbs-guard-refit",
        daemon=True,
    ).start()


def _refit_in_background(user_pk, generation) -> None:
    from django.db import connections

    try:
        refit(user_pk, generation)
    finally:
        connections.close_all()


def refit(user_pk, generation=None):
    try:
        fit = _fit(user_pk)
    except Exception:
        logger.warning("could not refit the DBS guard model", exc_info=True)
        fit = None
    with _lock:
        _refitting.discard(user_pk)
        if generation is not None and generation != _generation:
            return fit
        if fit is None:
            fit = _fits.get(user_pk) or PersonalFit(None, None, 0, _clock())
            fit.fitted_at = _clock()
            fit.scored = 0
        _fits[user_pk] = fit
    return fit


def _fit(user_pk) -> PersonalFit:
    window = list(
        requests_for(user_pk)
        .order_by("-created_at")
        .values_list("id", "features")[:WINDOW_ROWS]
    )
    newest = window[0][0] if window else None
    vectors = [to_vector(features) for _, features in window if isinstance(features, dict)]
    if len(vectors) < minimum_rows():
        return PersonalFit(None, newest, len(vectors), _clock())
    from sklearn.ensemble import IsolationForest

    rows = vectors + _prior_sample(len(vectors))
    forest = IsolationForest(
        n_estimators=PERSONAL_ESTIMATORS, contamination=0.05, random_state=7
    )
    forest.fit(rows)
    return PersonalFit((forest, calibrate(forest, rows)), newest, len(vectors), _clock())


def _prior_sample(personal_rows: int) -> list[list[float]]:
    rows = load_corpus()["rows"]
    share = max(0, min(len(rows), personal_rows * 4 - personal_rows))
    step = max(1, len(rows) // share) if share else 0
    return rows[::step][:share] if share else []


def forget(user_pk=None):
    global _generation

    with _lock:
        _generation += 1
        if user_pk is None:
            _fits.clear()
            _refitting.clear()
        else:
            _fits.pop(user_pk, None)
            _refitting.discard(user_pk)


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
