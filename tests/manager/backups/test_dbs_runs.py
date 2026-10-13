from __future__ import annotations

import os
import time

import pytest

from dbs import audit
from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.activity.services import ActivityService
from dbs.manager.backups.models import BackupFile
from dbs.manager.backups.repositories import BackupFileRepository, BackupPlanRepository
from dbs.manager.backups.services import BackupService
from dbs.manager.backups.services.backup_run_service import KEEP_MAX, TAKE_KEEP
from dbs.manager.backups.services.dbs_runs import QUARANTINE_SUFFIX, Progress
from dbs.manager.backups.storage import BackupStorage
from dbs.naming import backup_filename
from tests.manager.backups.support import BackupHost
from tests.manager.servers.support import (
    BACKUP_DIR,
    BACKUP_PASSPHRASE,
    connecting_to,
    dbs_backup,
)

CONNECT = "dbs.manager.servers.services.connection_service.connect"
pytestmark = pytest.mark.django_db


@pytest.fixture
def take(admin, server, run_jobs, entry):
    def run():
        with run_jobs():
            job = BackupService(admin).take(server.pk)
        return entry(job.pk)

    return run


def hosting(monkeypatch, server_root, **options) -> BackupHost:
    host = BackupHost(root=server_root, **options)
    monkeypatch.setattr(CONNECT, connecting_to(host))
    return host


def files(server) -> list[BackupFile]:
    return list(BackupFileRepository().alive_for_server(server.pk))


def stored_name(job) -> str:
    return BackupFileRepository().find_including_deleted(job.data["backup"]).name


def test_a_take_streams_a_verified_backup_and_leaves_no_copy_on_the_server(
    server, host, take, storage
):
    job = take()

    assert job.status == audit.SUCCEEDED
    [backup] = files(server)
    assert backup.validation == BackupFile.Validation.VERIFIED
    assert backup.failure == ""
    assert (storage / backup.storage_path).read_bytes() == dbs_backup(BACKUP_PASSPHRASE)
    assert host.remote_names() == []
    assert job.data["released"] == 1


def test_the_backups_waiting_on_the_server_are_collected_first(
    server, host, take, storage
):
    older = host.keep_on_server(
        backup_filename("web-1", ordinal=7), dbs_backup(BACKUP_PASSPHRASE)
    )

    job = take()

    assert job.status == audit.SUCCEEDED
    assert job.data["pulled"] == 1
    assert host.pulls == [older]
    collected = BackupFileRepository().active().get(name=older.rsplit("/", 1)[1])
    assert collected.validation == BackupFile.Validation.VERIFIED
    assert collected.remote_size == collected.size
    assert collected.remote_mtime is not None
    assert collected.remote_path == ""
    assert len(files(server)) == 2
    assert host.remote_names() == []


def test_only_this_takes_prefix_is_collected(server, host, take):
    other = host.keep_on_server(backup_filename("web-1-nightly"), b"another plan")
    unrelated = host.keep_on_server("notes.txt", b"not a backup")

    take()

    assert host.pulls == []
    assert sorted(host.remote_names()) == sorted(
        [other.rsplit("/", 1)[1], unrelated.rsplit("/", 1)[1]]
    )


def test_a_backup_already_held_is_not_pulled_again(
    admin, server, host, make_plan, ran
):
    plan = make_plan(keep_remote=3)
    first = ran(plan)
    host.pulls.clear()

    second = ran(plan)

    assert second.data["pulled"] == 0
    assert host.pulls == []
    assert host.digests == [f"{BACKUP_DIR}/{stored_name(first)}"]


def test_a_server_copy_that_changed_under_its_name_is_pulled_again(
    server, host, make_plan, ran
):
    plan = make_plan(keep_remote=3)
    first = ran(plan)
    name = stored_name(first)
    (host.on_server(BACKUP_DIR) / name).write_bytes(
        bytes(reversed(dbs_backup(BACKUP_PASSPHRASE)))
    )
    host.pulls.clear()

    second = ran(plan)

    assert host.pulls == [f"{BACKUP_DIR}/{name}"]
    assert second.status == audit.SUCCEEDED
    assert second.data["quarantined"]


def test_a_broken_stream_is_kept_on_the_server_and_collected_next_time(
    monkeypatch, server, server_root, take, storage
):
    broken = hosting(monkeypatch, server_root, breaks=True)

    kept = take()

    assert kept.status == audit.SUCCEEDED
    assert kept.data == {"outcome": "kept_on_server", "pulled": 0}
    assert files(server) == []
    [waiting] = broken.remote_names()
    assert [path.name for path in (storage / str(server.pk)).iterdir()] == []

    healthy = hosting(monkeypatch, server_root)
    collected = take()

    assert collected.status == audit.SUCCEEDED
    assert collected.data["pulled"] == 1
    assert healthy.pulls == [f"{BACKUP_DIR}/{waiting}"]
    assert waiting in {file.name for file in files(server)}
    assert healthy.remote_names() == []


def test_a_streamed_backup_that_arrives_changed_is_quarantined(
    monkeypatch, server, server_root, take, storage
):
    good = dbs_backup(BACKUP_PASSPHRASE)
    host = hosting(monkeypatch, server_root, sent=bytes(reversed(good)))

    job = take()

    assert job.status == audit.FAILED
    assert job.error_code == "backup_quarantined"
    [quarantined] = files(server)
    assert job.data == {
        "output": "The bytes that arrived are not the ones the server sent.",
        "quarantined": [str(quarantined.pk)],
    }
    assert quarantined.validation == BackupFile.Validation.FAILED
    assert quarantined.failure == job.data["output"]
    assert quarantined.name.endswith(QUARANTINE_SUFFIX)
    assert (storage / quarantined.storage_path).is_file()
    [kept] = host.remote_names()
    assert quarantined.remote_path == f"{BACKUP_DIR}/{kept}"


def test_a_quarantined_backup_is_never_restored(
    api, monkeypatch, server, server_root, take
):
    hosting(monkeypatch, server_root, sent=b"garbage")
    take()
    [quarantined] = files(server)

    response = api.post(
        f"/api/backups/{quarantined.pk}/restore/",
        {"mode": "merge", "rehearse": True},
        format="json",
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "backup_quarantined"


def test_the_server_copy_of_a_quarantined_stream_is_collected_whole_next_time(
    monkeypatch, server, server_root, take
):
    hosting(monkeypatch, server_root, sent=b"cut short")
    take()
    [kept] = BackupHost(root=server_root).remote_names()

    host = hosting(monkeypatch, server_root)
    job = take()

    assert job.status == audit.SUCCEEDED
    assert host.pulls == [f"{BACKUP_DIR}/{kept}"]
    good = [file for file in files(server) if not file.failure]
    assert kept in {file.name for file in good}
    assert host.remote_names() == []


def test_a_backup_made_with_another_passphrase_is_quarantined_with_the_reason(
    monkeypatch, server, server_root, take
):
    hosting(monkeypatch, server_root, content=dbs_backup("another-passphrase"))

    job = take()

    assert job.error_code == "backup_quarantined"
    assert "Decryption" in files(server)[0].failure


def test_a_waiting_file_that_is_not_a_backup_is_quarantined_once(
    server, host, take
):
    garbage = host.keep_on_server(backup_filename("web-1", ordinal=9), b"not a backup")

    first = take()
    second = take()

    assert first.status == second.status == audit.SUCCEEDED
    [quarantined] = [file for file in files(server) if file.failure]
    assert first.data["quarantined"] == [str(quarantined.pk)]
    assert "quarantined" not in second.data
    assert host.pulls == [garbage]
    assert garbage.rsplit("/", 1)[1] in host.remote_names()


def test_the_server_keeps_the_newest_copies_a_plan_asks_for(
    server, host, make_plan, ran
):
    plan = make_plan(keep_remote=2)

    jobs = [ran(plan) for _ in range(3)]

    names = [stored_name(job) for job in jobs]
    assert host.remote_names() == sorted(names[1:])
    oldest = BackupFileRepository().find_including_deleted(jobs[0].data["backup"])
    assert oldest.remote_path == ""
    assert jobs[-1].data["released"] == 1


def test_a_server_copy_that_is_not_the_recorded_file_is_left_alone(
    server, host, make_plan, ran
):
    plan = make_plan(keep_remote=1)
    name = stored_name(ran(plan))
    (host.on_server(BACKUP_DIR) / name).write_bytes(b"replaced on the server")
    BackupPlanRepository().update(plan, keep_remote=0)

    ran(plan)

    assert name in host.remote_names()
    assert f"{BACKUP_DIR}/{name}" not in host.removed


def test_retention_keeps_at_most_five_good_backups_and_never_counts_quarantined(
    monkeypatch, server, server_root, take
):
    hosting(monkeypatch, server_root, sent=b"broken")
    take()
    host = hosting(monkeypatch, server_root)
    for _ in range(TAKE_KEEP + 2):
        take()

    good = [file for file in files(server) if not file.failure]
    quarantined = [file for file in files(server) if file.failure]
    assert len(good) == TAKE_KEEP
    assert len(quarantined) == 1
    assert host.remote_names() == []


def test_a_plan_never_keeps_more_than_five(server, host, make_plan, ran):
    plan = make_plan(keep=7, keep_remote=0)

    for _ in range(KEEP_MAX + 2):
        ran(plan)

    assert BackupFileRepository().alive_for_plan(plan.pk).count() == KEEP_MAX


def test_a_quarantined_arrival_never_pushes_out_a_good_backup(
    monkeypatch, server, server_root, make_plan, ran
):
    plan = make_plan(keep=1, keep_remote=0)
    hosting(monkeypatch, server_root)
    good = ran(plan)
    hosting(monkeypatch, server_root, sent=b"broken")

    failed = ran(plan)

    assert failed.error_code == "backup_quarantined"
    assert BackupFileRepository().find(good.data["backup"]) is not None


def test_retention_keeps_the_newest_by_the_moment_in_the_name(
    server, host, take
):
    for ordinal in range(1, TAKE_KEEP + 2):
        host.keep_on_server(
            f"web-1-2020010{ordinal}-000000Z.dbs", dbs_backup(BACKUP_PASSPHRASE)
        )

    job = take()

    kept = {file.name for file in files(server)}
    assert stored_name(job) in kept
    assert "web-1-20200101-000000Z.dbs" not in kept
    assert "web-1-20200102-000000Z.dbs" not in kept
    assert len(kept) == TAKE_KEEP


def test_stale_partials_on_the_manager_are_swept_before_a_run(server, host, take, storage):
    directory = BackupStorage().directory(server.pk)
    stale = directory / ".incoming-0123456789abcdef.part"
    stale.write_bytes(b"left by a crash")
    old = time.time() - 7200
    os.utime(stale, (old, old))

    take()

    assert not stale.exists()


def test_progress_reports_the_bytes_received_at_most_once_a_second(
    admin, server, monkeypatch
):
    job = ActivityService(admin).queue("backup.take", server=server, detail={"plan": "x"})
    ActivityService(admin).start(job.pk)
    clock = iter([10.0, 10.5, 11.2])
    monkeypatch.setattr("dbs.manager.backups.services.dbs_runs.time.monotonic", lambda: next(clock))
    report = Progress(ActivityRepository().get(job.pk), "stream")

    report(100)
    report(200)
    report(300)

    assert ActivityRepository().get(job.pk).data == {
        "plan": "x",
        "step": "stream",
        "received": 300,
    }
