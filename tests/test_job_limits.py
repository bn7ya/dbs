import io
import json

import pytest

from dbs import job_process
from dbs.exceptions import ConfigurationError


@pytest.mark.parametrize(
    "spec, expected",
    [
        ("0", 0),
        ("512", 512),
        ("512M", 512 * 1024 ** 2),
        ("2G", 2 * 1024 ** 3),
        ("2 GiB", 2 * 1024 ** 3),
        ("64mb", 64 * 1024 ** 2),
        (1024, 1024),
    ],
)
def test_sizes_read_the_usual_units(spec, expected):
    assert job_process.parse_size(spec) == expected


@pytest.mark.parametrize("spec", ["lots", "-1G", "2X"])
def test_an_unreadable_size_names_the_forms(spec):
    with pytest.raises(ConfigurationError, match="512M"):
        job_process.parse_size(spec)


def test_exit_codes_name_their_reason():
    for reason, code in job_process.EXIT_CODES.items():
        assert job_process.reason_of(code) == reason
    assert job_process.reason_of(-9) == job_process.KILLED
    assert job_process.reason_of(1) == job_process.KILLED


def test_the_child_gets_the_settings_module_and_the_parents_path(monkeypatch):
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "tests.settings")

    environment = job_process.child_environment()

    assert environment["DJANGO_SETTINGS_MODULE"] == "tests.settings"
    assert "" not in environment["PYTHONPATH"].split(":")


def test_a_spec_carries_the_limits_but_not_into_the_command(settings):
    settings.DBS_JOB_TIME_LIMIT = "30m"
    settings.DBS_JOB_MEMORY_LIMIT = "1G"
    settings.DBS_JOB_NICE = 5

    spec = job_process.spec_for(kind="backup", owner="o", passphrase="secret")

    assert (spec["time_limit"], spec["memory_limit"], spec["nice"]) == (1800, 1024 ** 3, 5)
    assert "secret" not in " ".join(job_process.command())


def test_the_child_reads_its_spec_from_one_line_and_reports_json(monkeypatch, capsys):
    monkeypatch.setattr(job_process, "_bootstrap", lambda path: None)
    monkeypatch.setattr(job_process, "run", lambda spec: {"output": spec["kind"]})
    spec = {"kind": "scheduled", "owner": "o", "time_limit": 60, "memory_limit": 0, "nice": 0}

    assert job_process.main(io.StringIO(json.dumps(spec) + "\n")) == 0

    assert json.loads(capsys.readouterr().out) == {"output": "scheduled"}


def test_the_last_json_line_of_a_child_is_its_result():
    assert job_process._last_json(b"noise\n{\"output\": \"x\"}\n") == {"output": "x"}
    assert job_process._last_json(b"no json at all") == {}


def test_the_watchdog_stops_a_job_past_its_time(monkeypatch):
    clock = iter([0.0, 100.0])
    monkeypatch.setattr(job_process.time, "monotonic", lambda: next(clock))
    limits = job_process.Limits(
        {"time_limit": 10, "memory_limit": 0, "owner": "o"}, lambda reason: None
    )

    assert limits.breached() == job_process.TIME_LIMIT


def test_the_watchdog_stops_a_job_over_its_memory(monkeypatch):
    monkeypatch.setattr(job_process, "resident_bytes", lambda pid="self": 900)
    limits = job_process.Limits(
        {"time_limit": 3600, "memory_limit": 500, "owner": "o"}, lambda reason: None
    )

    assert limits.breached() == job_process.MEMORY_LIMIT
