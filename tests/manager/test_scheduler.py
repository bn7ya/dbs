import time
from datetime import timedelta

import pytest
from django.utils import timezone

from dbs import leases
from dbs.manager import scheduler
from dbs.manager.conf import INSTANCE_LEASE
from dbs.manager.models import ScheduledTask
from dbs.manager.scheduler import TASKS, Scheduler, claim, tick

calls = []


def record_run():
    task = ScheduledTask.objects.get(name="test_task")
    calls.append(task.next_run_at)


@pytest.fixture
def test_task(db, monkeypatch):
    calls.clear()
    monkeypatch.setitem(
        TASKS,
        "test_task",
        (timedelta(minutes=5), "tests.manager.test_scheduler.record_run"),
    )
    return ScheduledTask.objects.create(
        name="test_task", next_run_at=timezone.now() - timedelta(seconds=1)
    )


@pytest.mark.django_db
def test_the_migration_seeds_every_scheduled_task():
    assert set(ScheduledTask.objects.values_list("name", flat=True)) == set(TASKS)


def test_a_due_task_runs_once_and_moves_its_next_run_first(test_task):
    now = timezone.now()

    assert "test_task" in tick(now=now)

    assert calls == [now + timedelta(minutes=5)]
    assert "test_task" not in tick(now=now)
    assert len(calls) == 1


def test_a_task_that_is_not_due_does_not_run(test_task):
    ScheduledTask.objects.filter(name="test_task").update(
        next_run_at=timezone.now() + timedelta(hours=1)
    )

    assert "test_task" not in tick()
    assert calls == []


def test_a_row_with_no_handler_is_left_alone(db):
    when = timezone.now() - timedelta(minutes=1)
    ScheduledTask.objects.create(name="retired_task", next_run_at=when)

    assert "retired_task" not in tick()
    assert ScheduledTask.objects.get(name="retired_task").next_run_at == when


def test_a_task_claimed_elsewhere_is_not_claimed_again(test_task):
    following = timezone.now() + timedelta(minutes=5)

    assert claim("test_task", test_task.next_run_at, following)
    assert not claim("test_task", test_task.next_run_at, following)


def test_nothing_runs_while_another_instance_holds_the_lease(test_task):
    assert leases.acquire(INSTANCE_LEASE, "elsewhere:1", 60)

    assert tick() == []
    assert calls == []


def test_a_tick_renews_the_instance_lease(test_task):
    tick()

    assert leases.holder(INSTANCE_LEASE).owner == leases.process_owner()


def test_the_thread_ticks_until_stopped(monkeypatch):
    ticks = []
    monkeypatch.setattr(scheduler, "tick", lambda: ticks.append(1) or [])
    monkeypatch.setattr(scheduler, "close_old_connections", lambda: None)

    running = Scheduler(interval=0.01).start()
    while len(ticks) < 3:
        time.sleep(0.01)
    running.stop()
    count = len(ticks)
    time.sleep(0.05)

    assert running.thread is None
    assert len(ticks) == count


def test_a_failing_tick_does_not_stop_the_thread(monkeypatch, caplog):
    def failing():
        raise RuntimeError("boom")

    monkeypatch.setattr(scheduler, "tick", failing)
    monkeypatch.setattr(scheduler, "close_old_connections", lambda: None)

    assert Scheduler().safe_tick() == []
    assert "boom" in caplog.text
