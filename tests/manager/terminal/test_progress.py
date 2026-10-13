from __future__ import annotations

import time
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from dbs.manager.activity import heartbeat
from dbs.manager.terminal import progress


def session(as_json=False):
    return SimpleNamespace(out=SimpleNamespace(as_json=as_json))


@pytest.fixture
def pulse():
    started = heartbeat.begin(7)
    yield started
    heartbeat.end(7)


def test_a_long_job_prints_how_its_connection_is_doing(pulse, capsys):
    with pulse.connected():
        pulse(5 * 1024 * 1024)
        with progress.reported(session(), every=0.01):
            time.sleep(0.1)

    printed = capsys.readouterr().out.splitlines()
    assert "  connection alive, 5.0 MB moved" in printed


def test_a_silent_connection_is_reported_lost(pulse, settings):
    with pulse.connected():
        pulse.heard_at = timezone.now() - timedelta(
            seconds=4 * settings.SSH_KEEPALIVE_INTERVAL
        )
        shown = progress.line(pulse.beat())

    assert shown.startswith("connection lost: nothing heard for ")
    assert shown.endswith(", 0 bytes moved")


def test_work_without_a_connection_is_shown_as_local(pulse):
    pulse(512)

    assert progress.line(pulse.beat()) == "working here, 512 bytes moved"


def test_json_output_gets_no_progress_lines(pulse, capsys):
    with pulse.connected(), progress.reported(session(as_json=True), every=0.01):
        time.sleep(0.05)

    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    ("count", "shown"),
    [(0, "0 bytes"), (1536, "1.5 KB"), (3 * 1024**3, "3.0 GB"), (5 * 1024**4, "5.0 TB")],
)
def test_sizes_read_as_people_say_them(count, shown):
    assert progress.size(count) == shown
