"""The base model that ships pre-trained, so scoring works from the first request."""

import statistics

import pytest

from dbs.exceptions import ConfigurationError
from dbs.security import baseline, synthetic
from dbs.security.detector import normalise
from dbs.security.features import FEATURE_NAMES, SCHEMA_VERSION

WARN = 0.60

LOGOUT = 0.85


@pytest.fixture(scope="module")
def calibration():
    return baseline.base_calibration()


def risk(rows, calibration):
    return [normalise(raw, calibration) for raw in baseline.base_model().score_samples(rows)]


def test_the_corpus_ships_with_the_package():
    assert baseline.CORPUS_PATH.is_file()
    assert baseline.CORPUS_PATH.stat().st_size < 512 * 1024


def test_the_corpus_matches_the_live_feature_schema():
    corpus = baseline.load_corpus()
    assert corpus["schema_version"] == SCHEMA_VERSION
    assert tuple(corpus["feature_names"]) == FEATURE_NAMES
    assert len(corpus["rows"]) >= 1000
    assert all(len(row) == len(FEATURE_NAMES) for row in corpus["rows"])


def test_a_corpus_from_another_schema_is_refused(tmp_path, monkeypatch):
    import gzip
    import json

    path = tmp_path / "baseline.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(
            {"schema_version": SCHEMA_VERSION + 1, "feature_names": list(FEATURE_NAMES), "rows": []},
            handle,
        )
    monkeypatch.setattr(baseline, "CORPUS_PATH", path)
    baseline.reset()
    try:
        with pytest.raises(ConfigurationError):
            baseline.load_corpus()
    finally:
        baseline.reset()


def test_a_corpus_built_from_other_features_is_refused(tmp_path, monkeypatch):
    import gzip
    import json

    path = tmp_path / "baseline.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(
            {"schema_version": SCHEMA_VERSION, "feature_names": ["only_one"], "rows": []},
            handle,
        )
    monkeypatch.setattr(baseline, "CORPUS_PATH", path)
    baseline.reset()
    try:
        with pytest.raises(ConfigurationError):
            baseline.load_corpus()
    finally:
        baseline.reset()


def test_ordinary_traffic_stays_below_the_warn_threshold(calibration):
    scores = sorted(risk(baseline.load_corpus()["rows"], calibration))
    assert statistics.mean(scores) < 0.30
    assert scores[int(len(scores) * 0.95)] < WARN


def test_a_typical_office_request_is_unremarkable(calibration):
    assert risk([synthetic.typical_row()], calibration)[0] < WARN


@pytest.mark.parametrize(
    "attack", ["impossible_travel", "night_burst", "agent_switch"]
)
def test_the_model_catches_the_held_out_attacks(attack, calibration):
    scores = risk(synthetic.attack_rows()[attack], calibration)
    assert min(scores) >= LOGOUT, f"{attack} scored as low as {min(scores):.3f}"


def test_a_destructive_spree_at_least_warns(calibration):
    scores = risk(synthetic.attack_rows()["destructive_spree"], calibration)
    assert statistics.mean(scores) >= WARN


def test_the_corpus_is_reproducible():
    assert synthetic.normal_rows(50, seed=1) == synthetic.normal_rows(50, seed=1)
    assert synthetic.normal_rows(50, seed=1) != synthetic.normal_rows(50, seed=2)


def test_nothing_is_unpickled_to_build_the_model():
    source = (baseline.CORPUS_PATH.parent / "detector.py").read_text()
    corpus_source = (baseline.CORPUS_PATH.parent / "baseline.py").read_text()
    for text in (source, corpus_source):
        assert "pickle" not in text
        assert "joblib" not in text
