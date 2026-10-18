import json
import os
import signal
import subprocess
import sys
import time

import pytest

from dbs import audit
from dbs.models import AuditEvent, BackupSchedule
from tests.isolation.instance import BARRIER, BOOTSTRAP, LEASE
from tests.isolation.test_job_process import alive, backup_dir  # noqa: F401
from tests.testapp.models import Author

pytestmark = pytest.mark.django_db(transaction=True)

INSTANCES = 3
LEASE_SECONDS = 3


def start(action, folder, barrier, **environment):
    environ = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "tests.isolation.settings",
        "DBS_ISOLATION_BACKUP_DIR": str(folder),
        "PYTHONPATH": os.pathsep.join(sys.path),
        BARRIER: str(barrier),
        **environment,
    }
    return subprocess.Popen(
        [sys.executable, "-m", "tests.isolation.instance", action],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environ,
        text=True,
        start_new_session=True,
    )


def said(process):
    line = process.stdout.readline()
    if not line:
        raise AssertionError(process.stderr.read()[-2000:])
    return json.loads(line)


def outcome(process):
    lines = [json.loads(line) for line in process.stdout.read().splitlines() if line]
    process.wait(60)
    assert process.returncode == 0, process.stderr.read()[-2000:]
    merged = {}
    for found in lines:
        merged.update(found)
    return merged


def backups_in(folder):
    return {
        name: os.path.getsize(os.path.join(folder, name))
        for name in os.listdir(folder)
        if os.path.getsize(os.path.join(folder, name))
    }


def children_of(pid):
    found = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat", encoding="ascii") as stat:
                fields = stat.read().rsplit(")", 1)[1].split()
        except OSError:
            continue
        if int(fields[1]) == pid:
            found.append(int(entry))
    return found


def test_three_instances_take_a_due_scheduled_backup_exactly_once(
    backup_dir, tmp_path  # noqa: F811
):
    BackupSchedule.objects.create(enabled=True, interval="6h")
    Author.objects.create(name="Ada")
    barrier = tmp_path / "go"
    instances = [start("scheduled", backup_dir, barrier) for _ in range(INSTANCES)]
    for instance in instances:
        said(instance)

    barrier.write_text("go")
    results = [outcome(instance) for instance in instances]

    assert sum(1 for result in results if result.get("output")) == 1
    assert len(backups_in(backup_dir)) == 1
    succeeded = AuditEvent.objects.filter(action="backup.create", status=audit.SUCCEEDED)
    assert succeeded.count() == 1
    assert BackupSchedule.load().last_status == audit.SUCCEEDED


def test_two_instances_asked_for_a_backup_at_once_run_one_and_refuse_the_other(
    backup_dir, tmp_path  # noqa: F811
):
    Author.objects.create(name="Ada")
    barrier = tmp_path / "go"
    instances = [start("backup", backup_dir, barrier) for _ in range(2)]
    for instance in instances:
        said(instance)

    barrier.write_text("go")
    results = [outcome(instance) for instance in instances]

    assert sorted(bool(result.get("busy")) for result in results) == [False, True]
    [taken] = [result for result in results if not result.get("busy")]
    assert taken["status"] == audit.SUCCEEDED
    assert len(backups_in(backup_dir)) == 1


def test_an_instance_killed_with_its_job_lets_another_instance_back_up(
    backup_dir, tmp_path  # noqa: F811
):
    Author.objects.create(name="Ada")
    held = tmp_path / "held"
    never = tmp_path / "never"
    first = start(
        "hold",
        backup_dir,
        held,
        **{
            LEASE: str(LEASE_SECONDS),
            BOOTSTRAP: "tests.isolation.hooks.slow",
            "DBS_TEST_BARRIER": str(never),
        },
    )
    said(first)
    held.write_text("go")
    event_id = said(first)["event"]
    stop = time.monotonic() + 30
    while not children_of(first.pid) and time.monotonic() < stop:
        time.sleep(0.05)
    jobs_running = children_of(first.pid)
    assert jobs_running

    for pid in [*jobs_running, first.pid]:
        os.kill(pid, signal.SIGKILL)
    first.wait(10)
    stop = time.monotonic() + 10
    while any(alive(pid) for pid in jobs_running) and time.monotonic() < stop:
        time.sleep(0.05)
    time.sleep(LEASE_SECONDS + 1)

    again = tmp_path / "again"
    second = start("backup", backup_dir, again, **{LEASE: str(LEASE_SECONDS)})
    said(second)
    again.write_text("go")
    result = outcome(second)

    assert result["status"] == audit.SUCCEEDED
    abandoned = AuditEvent.objects.get(pk=event_id)
    assert (abandoned.status, abandoned.error_code) == (audit.FAILED, audit.INTERRUPTED)
    assert len(backups_in(backup_dir)) == 1
