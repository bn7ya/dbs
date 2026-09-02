from __future__ import annotations

import gzip
import json
from functools import lru_cache
from pathlib import Path

from ..exceptions import ConfigurationError
from .features import FEATURE_NAMES, SCHEMA_VERSION

CORPUS_PATH = Path(__file__).with_name("baseline.json.gz")


def write_corpus(rows, seed, generated):
    rows = [[round(value, 4) for value in row] for row in rows]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "feature_names": list(FEATURE_NAMES),
        "seed": seed,
        "generated": generated,
        "rows": rows,
    }
    with gzip.open(CORPUS_PATH, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"))
    return CORPUS_PATH


@lru_cache(maxsize=1)
def load_corpus():
    if not CORPUS_PATH.exists():
        raise ConfigurationError(
            f"The DBS base model corpus is missing from {CORPUS_PATH}. Reinstall "
            "django-dbs, or regenerate it with scripts/train_base_model.py."
        )
    with gzip.open(CORPUS_PATH, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ConfigurationError(
            f"The base model corpus is schema version "
            f"{payload.get('schema_version')} but this DBS expects "
            f"{SCHEMA_VERSION}. Regenerate it with scripts/train_base_model.py."
        )
    if tuple(payload.get("feature_names", ())) != FEATURE_NAMES:
        raise ConfigurationError(
            "The base model corpus was built from a different feature set. "
            "Regenerate it with scripts/train_base_model.py."
        )
    return payload


@lru_cache(maxsize=1)
def base_model():
    from sklearn.ensemble import IsolationForest

    rows = load_corpus()["rows"]
    forest = IsolationForest(
        n_estimators=120,
        contamination=0.02,
        random_state=20260302,
    )
    forest.fit(rows)
    return forest


@lru_cache(maxsize=1)
def base_calibration():
    return calibrate(base_model(), load_corpus()["rows"])


def calibrate(forest, rows):
    scores = sorted(forest.score_samples(rows))
    middle = scores[len(scores) // 2]
    tail = scores[max(0, int(len(scores) * 0.02))]
    return middle, tail


def reset():
    load_corpus.cache_clear()
    base_model.cache_clear()
    base_calibration.cache_clear()
