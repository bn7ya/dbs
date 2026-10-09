import threading

import pytest

from dbs.manager import runner
from dbs.manager.runner import JobRunner, get_runner


def test_inline_jobs_run_at_once_in_the_calling_thread(settings):
    settings.DBS_MANAGER_JOBS_INLINE = True
    seen = []

    future = JobRunner().submit(
        lambda value: seen.append(threading.get_ident()) or value, 7
    )

    assert future.result() == 7
    assert seen == [threading.get_ident()]


def test_an_inline_job_that_fails_raises_to_the_caller(settings):
    settings.DBS_MANAGER_JOBS_INLINE = True

    def failing():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        JobRunner().submit(failing)


@pytest.fixture
def connections(monkeypatch):
    calls = []

    class FakeConnection:
        def close(self):
            calls.append("close")

    monkeypatch.setattr(runner, "close_old_connections", lambda: calls.append("old"))
    monkeypatch.setattr(runner, "connection", FakeConnection())
    return calls


def test_a_threaded_job_runs_in_a_worker_between_connection_cleanups(
    settings, connections
):
    settings.DBS_MANAGER_JOBS_INLINE = False
    pool = JobRunner(workers=1)
    seen = []

    def job():
        connections.append("job")
        seen.append(threading.get_ident())
        return "done"

    try:
        assert pool.submit(job).result(timeout=5) == "done"
    finally:
        pool.shutdown()

    assert seen != [threading.get_ident()]
    assert connections == ["old", "job", "close"]


def test_a_threaded_job_that_fails_is_logged_and_still_closes(
    settings, connections, caplog
):
    settings.DBS_MANAGER_JOBS_INLINE = False
    pool = JobRunner(workers=1)

    def failing():
        raise RuntimeError("boom")

    try:
        future = pool.submit(failing)
        with pytest.raises(RuntimeError):
            future.result(timeout=5)
    finally:
        pool.shutdown()

    assert connections == ["old", "close"]
    assert "failed" in caplog.text


def test_shutdown_stops_the_pool_and_a_later_job_starts_it_again(settings, connections):
    settings.DBS_MANAGER_JOBS_INLINE = False
    pool = JobRunner(workers=1).start()
    assert pool.running

    pool.shutdown()
    assert not pool.running
    assert pool.submit(lambda: 1).result(timeout=5) == 1
    pool.shutdown()


def test_there_is_one_runner_per_process():
    assert get_runner() is get_runner()
