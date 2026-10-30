from __future__ import annotations

import json

import pytest
from rest_framework.test import APIClient

from dbs import audit
from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.applications.repositories import ApplicationRepository
from dbs.manager.backups.repositories import BackupPlanRepository
from dbs.manager.backups.services.backup_plan_service import BackupPlanService
from dbs.manager.permissions import Role
from dbs.manager.relocation.locks import ServerMoveLock
from dbs.manager.servers.services import ServerConnectionService
from dbs.models import AuditEvent
from tests.manager.relocation.conftest import SOURCE, SUDO_PASSWORD, TARGET
from tests.manager.servers.support import BACKUP_PASSPHRASE, PASSWORD


def move(world, **body):
    return f"/api/servers/{world['source_server'].pk}/move/", {
        "target_server": str(world["target_server"].pk),
        "applications": [
            {
                "application": str(world["application"].pk),
                "name": "shop-new",
                "folder": str(world["target_folder"]),
            }
        ],
        **body,
    }


def started(api, world, run_jobs, **body):
    url, payload = move(world, **body)
    with run_jobs():
        response = api.post(url, payload, format="json")
    assert response.status_code == 202, response.json()
    return AuditEvent.objects.get(pk=response.json()["activity"])


def phase(job, name):
    return next(
        item
        for item in job.data["phases"]
        if item.get("name") == name or item["phase"] == name
    )


def statuses(job, name):
    return {step["step"]: step["status"] for step in phase(job, name)["steps"]}


def every_argv(world, host):
    return [entry["argv"] for entry in world["hosts"].everything(host)]


@pytest.mark.django_db
def test_a_rehearsal_plans_the_move_and_changes_nothing(api, world, run_jobs):
    job = started(api, world, run_jobs)

    assert job.status == audit.SUCCEEDED, job.data
    assert statuses(job, "plan") == {
        "connect": "succeeded",
        "inventory": "succeeded",
        "evaluate": "succeeded",
    }
    [plan] = job.data["inventory"]["applications"]
    assert plan["target_name"] == "shop-new"
    assert plan["folder"]["excluded"] == ["db.sqlite3", ".venv"]
    assert plan["git"]["remote"] == "https://github.com/org/shop.git"
    assert plan["database"]["placement"] == "file"
    assert plan["python"]["action"] == "rebuild"
    assert {note["code"] for note in plan["notes"]} >= {
        "git_remote_has_credentials",
        "venv_rebuilt",
    }
    assert job.data["inventory"]["target"]["system"]["codename"] == "noble"
    assert all(step["status"] == "pending" for step in phase(job, "shop")["steps"])
    assert not world["target_folder"].exists()
    assert all(entry["line"] is None for entry in world["target_host"].runs)
    assert not ApplicationRepository().name_in_use("shop-new")
    assert world["taken"] == []


@pytest.mark.django_db
def test_a_move_for_real_carries_the_application_and_restores_its_data(
    api, world, run_jobs
):
    job = started(
        api,
        world,
        run_jobs,
        rehearsal=False,
        password=PASSWORD,
        confirm_name="new",
        sudo_password=SUDO_PASSWORD,
    )

    assert job.status == audit.SUCCEEDED, (job.error_code, job.data.get("output"))
    shop = statuses(job, "shop")
    assert shop == {
        "source_backup": "succeeded",
        "carry_folder": "succeeded",
        "python": "succeeded",
        "register": "succeeded",
        "migrate": "succeeded",
        "restore": "succeeded",
        "final_check": "succeeded",
        "copy_plans": "succeeded",
    }
    landed = world["target_folder"]
    assert (landed / ".git" / "HEAD").read_text() == "ref: refs/heads/main\n"
    assert (landed / ".env").read_text() == "SECRET_KEY=moving\n"
    assert not (landed / "db.sqlite3").exists()
    assert "Django==5.2" in world["pip"] and "-e git" not in world["pip"]
    assert world["migrations"] == 1
    [restore] = world["restores"]
    assert "--flush" in restore["argv"] and restore["line"] == BACKUP_PASSPHRASE
    moved = ApplicationRepository().active().get(name="shop-new")
    assert moved.server_id == world["target_server"].pk
    assert moved.project_dir == str(landed)
    assert moved.deployment == {"runs_in": "host", "database": "sqlite"}
    assert ServerConnectionService(None).backup_passphrase(moved) == BACKUP_PASSPHRASE
    assert job.data["created_applications"] == [
        {"source": str(world["application"].pk), "target": str(moved.pk), "name": "shop-new"}
    ]
    assert ApplicationRepository().find(world["application"].pk).project_dir == str(
        world["project"]
    )
    assert (world["project"] / "db.sqlite3").exists()


@pytest.mark.django_db
def test_the_sudo_password_goes_only_to_sudo_and_is_kept_nowhere(api, world, run_jobs):
    job = started(
        api,
        world,
        run_jobs,
        rehearsal=False,
        password=PASSWORD,
        confirm_name="new",
        sudo_password=SUDO_PASSWORD,
    )

    lines = [entry for entry in world["target_host"].runs if entry["line"] == SUDO_PASSWORD]
    assert lines and all(entry["argv"][:2] == ["sudo", "-S"] for entry in lines)
    assert {entry["line"] for entry in world["source_host"].runs} <= {None, BACKUP_PASSPHRASE}
    events = AuditEvent.objects.all()
    assert not [event for event in events if SUDO_PASSWORD in json.dumps(event.data)]
    assert SUDO_PASSWORD not in json.dumps(job.data)


@pytest.mark.django_db
def test_nothing_runs_on_the_source_but_reads_and_the_backup(api, world, run_jobs):
    started(
        api,
        world,
        run_jobs,
        rehearsal=False,
        password=PASSWORD,
        confirm_name="new",
        sudo_password=SUDO_PASSWORD,
    )

    python = world["python"]
    for argv in every_argv(world, SOURCE):
        if argv[:1] == ["timeout"]:
            argv = argv[4:]
        allowed = (
            argv[:2] == ["tar", "--create"]
            or argv[0] in ("id", "uname", "getenforce", "du", "find", "df", "ss")
            or argv[:2] in (["sudo", "--version"], ["sudo", "-n"])
            or argv[:2] == ["git", "-C"]
            or argv[0] in ("docker", "podman") and argv[1] in ("version", "ps", "info")
            or argv[:1] == ["true"]
            or argv[0] == python
            and argv[1:3]
            in (["-c", argv[2]], ["-m", "pip"], ["manage.py", "shell"], ["manage.py", "dbs_backup"])
        )
        assert allowed, argv


@pytest.mark.django_db
def test_a_wrong_sudo_password_stops_before_anything_is_written(api, world, run_jobs):
    job = started(
        api,
        world,
        run_jobs,
        rehearsal=False,
        password=PASSWORD,
        confirm_name="new",
        sudo_password="not-it",
    )

    assert job.status == audit.FAILED
    assert job.error_code == "sudo_password_wrong"
    assert not world["target_folder"].exists()
    assert world["taken"] == []
    assert statuses(job, "prepare")["sudo_check"] == "failed"
    tries = [entry for entry in world["target_host"].runs if entry["argv"][:2] == ["sudo", "-S"]]
    assert len(tries) == 1


@pytest.mark.django_db
def test_a_folder_already_on_the_target_blocks_the_move(api, world, run_jobs):
    world["target_folder"].mkdir()
    (world["target_folder"] / "keep.txt").write_text("mine\n")

    job = started(api, world, run_jobs)

    assert job.status == audit.FAILED and job.error_code == "move_blocked"
    assert {blocker["code"] for blocker in job.data["blockers"]} == {"target_folder_not_empty"}
    assert (world["target_folder"] / "keep.txt").read_text() == "mine\n"


@pytest.mark.django_db
def test_a_move_for_real_needs_the_password_and_the_target_servers_name(api, world):
    url, payload = move(world, rehearsal=False)

    missing = api.post(url, payload, format="json")
    wrong_name = api.post(
        url, {**payload, "password": PASSWORD, "confirm_name": "old"}, format="json"
    )

    assert missing.json()["error"]["fields"] == {"password": ["required"]}
    assert wrong_name.json()["error"]["code"] == "confirm_name_mismatch"
    assert not ActivityRepository().filtered(action="relocation.move").exists()


@pytest.mark.django_db
def test_a_server_cannot_move_onto_itself(api, world):
    url, payload = move(world)
    payload["target_server"] = str(world["source_server"].pk)

    assert api.post(url, payload, format="json").json()["error"]["code"] == "same_server"


@pytest.mark.django_db
def test_only_applications_of_the_server_can_move(api, world, admin):
    url, payload = move(world)
    payload["applications"] = [{"application": "00000000-0000-0000-0000-000000000001"}]

    response = api.post(url, payload, format="json")

    assert response.status_code == 400
    assert "applications" in response.json()["error"]["fields"]


@pytest.mark.django_db
def test_one_move_at_a_time_per_server(api, world):
    ServerMoveLock().acquire([world["target_server"].pk], 999)
    url, payload = move(world)

    response = api.post(url, payload, format="json")

    assert response.json()["error"]["code"] == "server_move_running"


@pytest.mark.django_db
def test_an_operator_rehearses_but_cannot_move_for_real(world, run_jobs):
    operator = UserRepository().create(username="omar", password=PASSWORD, role=Role.OPERATOR)
    client = APIClient()
    client.force_login(operator)
    url, payload = move(world)

    with run_jobs():
        rehearsed = client.post(url, payload, format="json")
    real = client.post(
        url,
        {**payload, "rehearsal": False, "password": PASSWORD, "confirm_name": "new"},
        format="json",
    )

    assert rehearsed.status_code == 202
    assert real.json()["error"]["code"] == "role_required"


@pytest.mark.django_db
def test_backup_plans_are_copied_paused(api, world, run_jobs, admin):
    BackupPlanService(admin).create(
        application=world["application"].pk, kind="dbs", name="nightly", interval_minutes=1440
    )

    started(
        api,
        world,
        run_jobs,
        rehearsal=False,
        password=PASSWORD,
        confirm_name="new",
        sudo_password=SUDO_PASSWORD,
    )

    moved = ApplicationRepository().active().get(name="shop-new")
    [copied] = list(BackupPlanService(admin).list(moved.pk))
    assert (copied.name, copied.enabled) == ("nightly", False)
    assert BackupPlanRepository is not None


@pytest.mark.django_db
def test_a_stopped_move_resumes_where_it_stopped(api, world, run_jobs):
    failing = started(
        api,
        world,
        run_jobs,
        rehearsal=False,
        password=PASSWORD,
        confirm_name="new",
        sudo_password="not-it",
    )
    assert failing.status == audit.FAILED

    resumed = started(
        api,
        world,
        run_jobs,
        rehearsal=False,
        password=PASSWORD,
        confirm_name="new",
        sudo_password=SUDO_PASSWORD,
        resume_of=failing.pk,
    )

    assert resumed.status == audit.SUCCEEDED, (resumed.error_code, resumed.data.get("blockers"))
    assert ApplicationRepository().name_in_use("shop-new")


@pytest.mark.django_db
def test_a_rehearsal_cannot_be_resumed(api, world, run_jobs):
    rehearsed = started(api, world, run_jobs)
    url, payload = move(world, resume_of=rehearsed.pk)

    assert api.post(url, payload, format="json").json()["error"]["code"] == "move_not_resumable"


@pytest.mark.django_db
def test_every_step_is_audited_without_secrets(api, world, run_jobs):
    started(
        api,
        world,
        run_jobs,
        rehearsal=False,
        password=PASSWORD,
        confirm_name="new",
        sudo_password=SUDO_PASSWORD,
    )

    actions = set(ActivityRepository().filtered().values_list("action", flat=True))
    assert {"relocation.move", "relocation.carry_folder", "relocation.restore"} <= actions
    for event in AuditEvent.objects.filter(action__startswith="relocation."):
        assert PASSWORD not in json.dumps(event.data)
        assert SUDO_PASSWORD not in json.dumps(event.data)
    assert TARGET


@pytest.mark.django_db
def test_after_a_restart_move_locks_and_spools_of_finished_jobs_are_freed(world, settings):
    from dbs.manager import recovery
    from dbs.manager.conf import data_dir

    ServerMoveLock().acquire([world["source_server"].pk, world["target_server"].pk], 4242)
    spool = data_dir() / "relocation" / "4242"
    spool.mkdir(parents=True)
    (spool / "folder-1").write_bytes(b"partial")

    recovery.release_abandoned_locks()

    assert not ServerMoveLock().held(world["source_server"].pk)
    assert not ServerMoveLock().held(world["target_server"].pk)
    assert not spool.exists()


@pytest.mark.django_db
def test_a_server_that_a_move_holds_cannot_be_deleted(api, world, admin):
    from dbs.manager.servers.services import ServerService

    ServerMoveLock().acquire([world["target_server"].pk], 77)

    with pytest.raises(Exception) as refused:
        ServerService(admin).delete(world["target_server"].pk, account_password=PASSWORD)

    assert getattr(refused.value, "default_code", "") == "server_move_running"
