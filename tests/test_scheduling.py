"""Interval parsing and the shared schedule loop."""

import threading

import pytest

from dbs.exceptions import ConfigurationError
from dbs.scheduling import parse_interval, run_schedule


@pytest.mark.parametrize(
    "spec,seconds",
    [("90", 90), ("90s", 90), ("30m", 1800), ("6h", 21600), ("1d", 86400), (" 2H ", 7200)],
)
def test_parse_interval_accepts_supported_forms(spec, seconds):
    assert parse_interval(spec) == seconds


@pytest.mark.parametrize("spec", ["", "0", "0s", "-5m", "6hours", "1.5h", "soon", "h"])
def test_parse_interval_rejects_everything_else(spec):
    with pytest.raises(ConfigurationError):
        parse_interval(spec)


def test_once_runs_exactly_one_cycle():
    calls = []
    failures = run_schedule(lambda: calls.append(1), 3600, once=True)
    assert calls == [1]
    assert failures == 0


def test_a_preset_stop_prevents_any_cycle():
    calls = []
    stop = threading.Event()
    stop.set()
    run_schedule(lambda: calls.append(1), 1, stop=stop)
    assert calls == []


def test_loop_survives_a_failing_cycle_and_counts_it():
    stop = threading.Event()
    calls = []

    def action():
        calls.append(len(calls))
        if len(calls) == 1:
            raise RuntimeError("backup exploded")
        if len(calls) == 3:
            stop.set()

    failures = run_schedule(action, 0, stop=stop)

    assert len(calls) == 3
    assert failures == 1


def test_the_wait_is_shortened_by_the_time_the_cycle_took():
    waits = []
    stop = threading.Event()
    ticks = iter([0.0, 10.0, 20.0, 30.0])

    def action():
        if len(waits) >= 1:
            stop.set()

    original_wait = stop.wait

    def record_wait(timeout=None):
        waits.append(timeout)
        return original_wait(0)

    stop.wait = record_wait
    run_schedule(action, 60, stop=stop, clock=lambda: next(ticks))

    assert waits == [50.0, 50.0]
