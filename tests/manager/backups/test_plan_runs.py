from __future__ import annotations

from uuid import uuid4

import pytest

from dbs import audit
from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.backups.locks import TakeLock
from dbs.manager.backups.models import BackupPlan
from dbs.manager.backups.repositories import BackupFileRepository, BackupPlanRepository
from dbs.manager.backups.services import (
    BackupPlanService,
    BackupRunService,
    BackupService,
)
from dbs.manager.backups.storage import BackupStorage
from dbs.manager.servers.exceptions import RemoteCommandFailed, SSHUnreachable
from dbs.manager.servers.services import ServerService
from tests.manager.backups.support import BackupHost
from tests.manager.servers.support import connecting_to

CONNECT = "dbs.manager.servers.services.connection_service.connect"


def run_url(plan) -> str:
    return f"/api/backups/plans/{plan.pk}/run/"


def stored(plan) -> BackupPlan:
    return BackupPlanRepository().get(plan.pk)


def logged(action: str):
    return list(ActivityRepository().filtered(action=action))


def alive(plan) -> list[str]:
    return [file.name for file in BackupFileRepository().alive_for_plan(plan.pk)]


@pytest.mark.django_db
def test_a_run_answers_at_once_with_the_job_and_whose_run_it_is(
    api, admin, server, host, make_plan, entry
):
    plan = make_plan()

    response = api.post(run_url(plan))

    assert response.status_code == 202
    assert set(response.json()) == {"activity"}
    job = entry(response.json()["activity"])
    assert (job.action, job.status) == ("backup.run", audit.QUEUED)
    assert (job.subject, job.target_name, job.actor) == (
        str(server.pk),
        "django-dbs",
        admin,
    )
    assert job.data == {"plan": str(plan.pk)}
    assert job.remote_addr == "127.0.0.1"
    assert host.takes == []


@pytest.mark.django_db
def test_a_disabled_or_manual_plan_still_runs_when_asked(api, make_plan, ran):
    for plan in (
        make_plan(name="off", enabled=False),
        make_plan(name="manual", interval_minutes=None),
    ):
        assert ran(plan).status == audit.SUCCEEDED


@pytest.mark.django_db
def test_a_plan_or_server_that_is_gone_is_not_run(api, admin, server, make_plan):
    deleted = make_plan(name="deleted")
    BackupPlanService(admin).delete(deleted.pk)
    orphan = make_plan(name="orphan")
    ServerService(admin).delete(server.pk)

    for path in (
        run_url(deleted),
        run_url(orphan),
        f"/api/backups/plans/{uuid4()}/run/",
    ):
        response = api.post(path)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
    assert logged("backup.run") == []


@pytest.mark.django_db
def test_takes_and_plan_runs_of_one_server_never_overlap(
    api, admin, server, host, make_plan, django_capture_on_commit_callbacks
):
    plan = make_plan()

    with django_capture_on_commit_callbacks():
        take = api.post("/api/backups/take/", {"server": server.pk})
        run = api.post(run_url(plan))
    TakeLock().release(server.pk, take.json()["activity"])
    with django_capture_on_commit_callbacks():
        first = api.post(run_url(plan))
        second_take = api.post("/api/backups/take/", {"server": server.pk})

    assert (take.status_code, first.status_code) == (202, 202)
    for refused in (run, second_take):
        assert refused.status_code == 409
        assert refused.json()["error"]["code"] == "backup_running"
    assert len(logged("backup.run")) == len(logged("backup.take")) == 1


@pytest.mark.django_db
def test_a_run_stores_a_backup_that_names_its_plan(admin, server, host, make_plan, ran):
    plan = make_plan(name="Nightly DB", keep_remote=3)

    job = ran(plan)

    assert job.status == audit.SUCCEEDED
    backup = BackupFileRepository().get(job.data["backup"])
    assert job.data == {
        "plan": str(plan.pk),
        "backup": str(backup.pk),
        "size": backup.size,
    }
    assert (backup.plan, backup.server, backup.created_by) == (plan, server, admin)
    assert backup.name.startswith("web-1-nightly-db-")
    [take] = host.takes
    assert (take.prefix, take.keep_remote) == ("web-1-nightly-db", 3)


@pytest.mark.django_db
def test_a_plan_named_with_nothing_a_file_name_can_carry_falls_back_to_its_id(
    host, make_plan, ran
):
    plan = make_plan(name="نسخة يومية")

    ran(plan)

    assert host.takes[0].prefix == f"web-1-plan-{plan.pk.hex[:8]}"


@pytest.mark.django_db
def test_keeping_no_copy_on_the_server_leaves_no_remote_path(host, make_plan, ran):
    job = ran(make_plan(keep_remote=0))

    assert host.takes[0].keep_remote == 0
    assert BackupFileRepository().get(job.data["backup"]).remote_path == ""


@pytest.mark.django_db
def test_a_finished_run_is_the_plans_last_run(make_plan, ran):
    plan = make_plan()

    job = ran(plan)

    plan = stored(plan)
    assert (plan.last_status, plan.last_error_code) == ("succeeded", "")
    assert plan.last_run_at == job.finished_at


@pytest.mark.django_db
def test_a_failed_run_is_the_plans_last_run_until_one_succeeds(
    monkeypatch, make_plan, ran
):
    plan = make_plan()
    monkeypatch.setattr(CONNECT, connecting_to(BackupHost(failure=SSHUnreachable())))

    failed = ran(plan)

    assert (failed.status, failed.error_code) == (
        audit.FAILED,
        "ssh_unreachable",
    )
    assert failed.data == {"plan": str(plan.pk)}
    assert (stored(plan).last_status, stored(plan).last_error_code) == (
        "failed",
        "ssh_unreachable",
    )
    assert stored(plan).last_run_at == failed.finished_at

    monkeypatch.setattr(CONNECT, connecting_to(BackupHost()))
    ran(plan)

    assert (stored(plan).last_status, stored(plan).last_error_code) == ("succeeded", "")


@pytest.mark.django_db
def test_a_remote_failure_keeps_the_plan_and_the_output(monkeypatch, make_plan, ran):
    plan = make_plan()
    monkeypatch.setattr(
        CONNECT, connecting_to(BackupHost(failure=RemoteCommandFailed(output="exit 1")))
    )

    failed = ran(plan)

    assert failed.data == {"plan": str(plan.pk), "output": "exit 1"}


@pytest.mark.django_db
def test_a_plan_deleted_before_its_run_starts_fails_it(
    admin, server, host, make_plan, django_capture_on_commit_callbacks, entry
):
    plan = make_plan()
    with django_capture_on_commit_callbacks() as queued:
        job = BackupPlanService(admin).run(plan.pk)
    BackupPlanService(admin).delete(plan.pk)

    for send in queued:
        send()

    assert entry(job.pk).error_code == "not_found"
    assert host.takes == []
    assert (
        BackupPlanRepository().all_including_deleted().get(pk=plan.pk).last_status
        == "none"
    )
    assert TakeLock().acquire(server.pk, uuid4())


@pytest.mark.django_db
def test_a_run_that_finds_the_server_busy_fails_with_backup_running(
    admin, server, host, make_plan, django_capture_on_commit_callbacks, entry
):
    plan = make_plan()
    with django_capture_on_commit_callbacks() as queued:
        job = BackupPlanService(admin).run(plan.pk)
    TakeLock().release(server.pk, job.pk)
    TakeLock().acquire(server.pk, uuid4())

    for send in queued:
        send()

    assert entry(job.pk).error_code == "backup_running"
    assert stored(plan).last_error_code == "backup_running"
    assert host.takes == []


@pytest.mark.django_db
def test_a_finished_run_is_not_run_twice(make_plan, host, ran):
    plan = make_plan()
    job = ran(plan)
    finished_at = stored(plan).last_run_at

    BackupRunService().run_plan(job.pk, plan.pk)

    assert len(host.takes) == 1
    assert stored(plan).last_run_at == finished_at


@pytest.mark.django_db
def test_a_run_keeps_the_plans_newest_files_and_deletes_the_rest(
    admin, server, storage, make_plan, ran, taken, entry
):
    plan = make_plan(keep=2)
    other = make_plan(name="weekly", keep=1)
    by_hand = taken()
    oldest, middle = ran(plan), ran(plan)
    ran(other)

    newest = ran(plan)

    names = {
        job.pk: BackupFileRepository().find_including_deleted(job.data["backup"]).name
        for job in (oldest, middle, newest)
    }
    assert alive(plan) == [names[newest.pk], names[middle.pk]]
    assert len(alive(other)) == 1
    assert BackupFileRepository().find(by_hand.pk) is not None
    [retention] = logged("backup.retention")
    assert retention.status == audit.SUCCEEDED
    assert (retention.subject, retention.target_name, retention.actor) == (
        str(server.pk),
        "django-dbs",
        admin,
    )
    assert retention.data == {"removed": [names[oldest.pk]], "plan": "django-dbs"}
    removed = BackupFileRepository().find_including_deleted(oldest.data["backup"])
    assert removed.is_deleted
    assert BackupStorage().exists(removed.storage_path)


@pytest.mark.django_db
def test_retention_counts_only_files_still_listed(api, make_plan, ran):
    plan = make_plan(keep=2)
    first = ran(plan)
    api.delete(f"/api/backups/{first.data['backup']}/")

    ran(plan)
    ran(plan)

    assert len(alive(plan)) == 2
    assert logged("backup.retention") == []


@pytest.mark.django_db
def test_a_file_removed_by_retention_can_be_brought_back(api, make_plan, ran):
    plan = make_plan(keep=1)
    first = ran(plan)
    ran(plan)

    response = api.post(f"/api/backups/{first.data['backup']}/undo-delete/")

    assert response.status_code == 200
    assert response.json()["plan"] == str(plan.pk)


@pytest.mark.django_db
def test_a_failed_run_deletes_nothing(monkeypatch, make_plan, ran):
    plan = make_plan(keep=1)
    ran(plan)
    monkeypatch.setattr(CONNECT, connecting_to(BackupHost(failure=SSHUnreachable())))

    ran(plan)

    assert len(alive(plan)) == 1
    assert logged("backup.retention") == []


@pytest.mark.django_db
def test_a_take_is_never_touched_by_retention(
    admin, server, host, run_jobs, make_plan, ran
):
    make_plan(keep=1)
    with run_jobs():
        BackupService(admin).take(server.pk)
    with run_jobs():
        BackupService(admin).take(server.pk)

    assert BackupFileRepository().alive_for_server(server.pk).count() == 2
