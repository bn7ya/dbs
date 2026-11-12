import threading
import time

import pytest

from dbs.manager.activity import heartbeat
from dbs.manager.activity.services import ActivityService
from dbs.manager.menu import commands, running
from dbs.manager.menu.results import ResultScreen

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def no_job_left_by_another_test(monkeypatch):
    monkeypatch.setattr(heartbeat, "_running", {})


@pytest.fixture
def job(admin):
    entry = ActivityService(admin).record(
        "backup.take", target="shop", detail={"step": "reading"}
    )
    pulse = heartbeat.begin(entry.pk)
    yield pulse
    heartbeat.end(entry.pk)


def test_a_running_job_is_described_by_its_target_its_step_and_its_connection(job):
    job(2048)

    assert running.progress() == ["shop, reading, working here, 2.0 KB moved"]


def test_a_job_with_an_open_connection_says_it_is_alive(job):
    with job.connected():
        assert running.progress() == ["shop, reading, connection alive, 0 bytes moved"]


def test_nothing_running_is_no_line():
    assert running.progress() == []


@pytest.mark.parametrize(
    "detail, step",
    [
        ({"step": "sending"}, "sending"),
        (
            {
                "steps": [
                    {"step": "migrate", "status": "succeeded"},
                    {"step": "restart", "status": "running"},
                ]
            },
            "restart",
        ),
        ({"current": "volumes"}, "volumes"),
        ({}, ""),
    ],
)
def test_the_step_is_read_from_what_each_kind_of_job_records(detail, step):
    assert running._step(detail) == step


def test_while_a_command_runs_the_page_is_repainted_with_its_progress(
    menu, monkeypatch
):
    monkeypatch.setattr(running, "EVERY", 0.05)
    monkeypatch.setattr(
        running, "progress", lambda: ["shop, sending, connection alive, 1.0 MB moved"]
    )
    monkeypatch.setattr(
        running, "handler_of", lambda args: lambda session: time.sleep(0.4)
    )
    menu.app.live = True

    outcome = running.run(menu.app, commands.verb("backup", "take"), {"--all": True})

    assert outcome.ok
    running_frames = [frame for frame in menu.frames if "Ctrl+C stops it." in frame]
    assert len(running_frames) >= 3
    assert any("connection alive, 1.0 MB moved" in frame for frame in running_frames)
    assert not any(
        thread.name == "dbs-manager-menu-progress" for thread in threading.enumerate()
    )


def test_progress_that_cannot_be_read_once_is_read_again(menu, monkeypatch):
    reads = []

    def unsteady():
        reads.append(len(reads))
        if len(reads) == 1:
            raise RuntimeError("database is locked")
        return ["shop, sending, connection alive, 1.0 MB moved"]

    monkeypatch.setattr(running, "EVERY", 0.05)
    monkeypatch.setattr(running, "progress", unsteady)
    monkeypatch.setattr(
        running, "handler_of", lambda args: lambda session: time.sleep(0.4)
    )
    menu.app.live = True

    outcome = running.run(menu.app, commands.verb("backup", "take"), {"--all": True})

    assert outcome.ok and len(reads) >= 3
    assert menu.saw("connection alive, 1.0 MB moved")


def test_once_it_ended_the_progress_is_gone(menu):
    screen = ResultScreen(menu.app, "Back up", running.Transcript())
    screen.progress = ["shop, sending"]

    screen.finish(running.Outcome(0, screen.transcript))

    assert screen.progress == ()
