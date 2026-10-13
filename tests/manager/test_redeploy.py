import json
from datetime import timedelta
from pathlib import Path

import pytest
from django.utils import timezone

from dbs import audit
from dbs.exceptions import RemoteTimeout
from dbs.manager.servers import settling
from dbs.manager.backups.locks import TakeLock
from dbs.manager.backups.models import BackupFile
from dbs.manager.backups.repositories import BackupFileRepository
from dbs.manager.backups.services.job_queue import JobQueue
from dbs.manager.backups.storage import BackupStorage
from dbs.manager.envfiles.models import EnvVersion
from dbs.manager.envfiles.repositories import EnvVersionRepository
from dbs.manager.envfiles.services import vault_contexts as env_contexts
from dbs.manager.redeploy.services import RedeployService
from dbs.manager.servers.models import Server
from dbs.manager.servers.repositories import ServerRepository
from dbs.manager.servers.services import ServerService
from dbs.manager.servers.services.server_service import DBS_VERSION
from dbs.manager.vault import fingerprint, seal, unseal
from dbs.models import AuditEvent
from tests.manager.remote import scripted_hosts
from tests.manager.servers.support import (
    BACKUP_PASSPHRASE,
    PASSWORD,
    dbs_backup,
    host_key_line,
    private_key_text,
)
from tests.manager.support import logged

REDEPLOY = "/api/redeploy/"
SOURCE = "10.0.0.5"
TARGET = "10.0.0.6"
PYTHON = "/srv/app/.venv/bin/python"
TARGET_PASSPHRASE = "target-passphrase-77e1"
ENV_CONTENT = b"SECRET_KEY=moved\nDEBUG=0\n"
TARGET_ENV = b"SECRET_KEY=fresh-install\nDEBUG=1\n"
STEPS = [
    "check",
    "source_backup",
    "record_env",
    "safety_backup",
    "env",
    "migrate",
    "restore",
    "final_check",
]
BACKUP_AND_FETCH = "dbs.manager.servers.gateways.ssh_gateway.backup_and_fetch"
MIGRATE = [PYTHON, "manage.py", "migrate", "--noinput"]
MIGRATE_CHECK = [PYTHON, "manage.py", "migrate", "--check", "--noinput"]


def add_server(admin, name, host, **fields):
    return ServerService(admin).create(
        name=name,
        host=host,
        username="deploy",
        auth_method=Server.AuthMethod.KEY,
        private_key=private_key_text(),
        host_key=host_key_line(),
        python_path=PYTHON,
        **fields,
    )


def stored_file(server, name, content):
    storage = BackupStorage()
    storage.directory(server.pk)
    path = f"{server.pk}/{name}"
    with storage.writing(path) as handle:
        handle.write(content)
    return BackupFileRepository().create(
        server=server,
        kind=BackupFile.Kind.DBS,
        name=name,
        size=len(content),
        sha256="0" * 64,
        storage_path=path,
        validation=BackupFile.Validation.STRUCTURE_OK,
    )


def stored_bytes(file_id):
    file = BackupFileRepository().find_including_deleted(file_id)
    with BackupStorage().open_read(file.storage_path) as handle:
        return handle.read()


@pytest.fixture
def world(admin, tmp_path, monkeypatch):
    target_root = tmp_path / "target"
    (target_root / "app").mkdir(parents=True)
    (target_root / "app" / ".env").write_bytes(TARGET_ENV)
    source = add_server(admin, "web-1", SOURCE, backup_passphrase=BACKUP_PASSPHRASE)
    target = add_server(
        admin,
        "web-2",
        TARGET,
        backup_passphrase=TARGET_PASSPHRASE,
        project_dir=str(target_root / "app"),
        remote_backup_dir=str(target_root / "backups"),
        env_path=str(target_root / "app" / ".env"),
    )
    backup = stored_file(source, "web-1-20261009-030000Z.dbs", b"DBS backup")
    version = EnvVersionRepository().create(
        server=source,
        path="/srv/app/.env",
        content_sealed=seal(ENV_CONTENT, context=env_contexts.CONTENT),
        fingerprint=fingerprint(ENV_CONTENT, context=env_contexts.CONTENT),
        size=len(ENV_CONTENT),
        key_names=["SECRET_KEY", "DEBUG"],
        source=EnvVersion.Source.PULLED,
    )
    hosts = scripted_hosts(monkeypatch)
    sent = {"restores": [], "taken": [], "events": []}

    def restore(argv, stdin_line):
        path = Path(argv[3])
        sent["restores"].append(
            {"argv": argv, "stdin": stdin_line, "data": path.read_bytes()}
        )
        sent["events"].append("restore")
        if "--dry-run" in argv:
            return 0, "12 records and 0 files would be restored\n", ""
        return 0, "Restored 12 records and 0 files\n", ""

    def migrate(argv, stdin_line):
        sent["events"].append("migrate")
        return 0, "No migrations to apply.\n", ""

    def backup_and_fetch(profile, passphrase, **options):
        made = dbs_backup(passphrase)
        (Path(options["dest_dir"]) / options["name"]).write_bytes(made)
        sent["taken"].append(
            {"host": profile.host, "passphrase": passphrase, "options": options}
        )
        sent["events"].append(f"backup {profile.host}")

    monkeypatch.setattr(BACKUP_AND_FETCH, backup_and_fetch)
    for argv, result in (
        (["uname", "-sr"], (0, "Linux 6.1\n", "")),
        ([PYTHON, "-c", DBS_VERSION], (0, "0.5.0\n", "")),
        ([PYTHON, "manage.py", "dbs_backup", "--help"], (0, "usage\n", "")),
        (MIGRATE_CHECK, (0, "", "")),
    ):
        hosts.answer(TARGET, argv, result)
    hosts.answer(TARGET, MIGRATE, migrate)
    hosts.answer(TARGET, [PYTHON, "manage.py", "dbs_restore"], restore)
    hosts.answer(SOURCE, ["true"], (0, "", ""))
    return {
        "source": source,
        "target": target,
        "backup": backup,
        "version": version,
        "hosts": hosts,
        "sent": sent,
        "root": target_root,
        "env": target_root / "app" / ".env",
    }


def body(world, **fields):
    values = {
        "source_server": str(world["source"].pk),
        "target_server": str(world["target"].pk),
        "backup": str(world["backup"].pk),
        "env_version": None,
        "flush": False,
        "rehearsal": True,
    }
    return {**values, **fields}


def for_real(world, **fields):
    return body(
        world,
        rehearsal=False,
        env_version=str(world["version"].pk),
        password=PASSWORD,
        confirm_name="web-2",
        **fields,
    )


def job_of(api, response):
    assert response.status_code == 202, response.json()
    assert set(response.json()) == {"activity"}
    return api.get(f"/api/activity/{response.json()['activity']}/").json()


def statuses(job):
    return [(step["step"], step["status"]) for step in job["detail"]["steps"]]


def moved(api, world, run_jobs, **fields):
    with run_jobs():
        response = api.post(REDEPLOY, for_real(world, **fields), format="json")
    return job_of(api, response)


def failing_migration(world):
    world["hosts"].answer(TARGET, MIGRATE, (1, "", "boom"))


def target_versions(world):
    return list(EnvVersionRepository().for_server(world["target"].pk))


@pytest.mark.django_db
def test_a_rehearsal_changes_nothing_on_either_server(api, world, run_jobs):
    with run_jobs():
        response = api.post(REDEPLOY, body(world), format="json")

    job = job_of(api, response)
    assert (job["action"], job["status"], job["error_code"]) == (
        "redeploy.run",
        "succeeded",
        "",
    )
    assert job["server"] == str(world["target"].pk)
    assert statuses(job) == [
        ("check", "succeeded"),
        ("source_backup", "succeeded"),
        ("record_env", "skipped"),
        ("safety_backup", "succeeded"),
        ("env", "skipped"),
        ("migrate", "skipped"),
        ("restore", "succeeded"),
        ("final_check", "skipped"),
    ]
    assert job["detail"]["source_reachable"] is True
    assert job["detail"]["target_had_data"] is True
    [restore] = world["sent"]["restores"]
    assert "--dry-run" in restore["argv"]
    assert restore["data"] == b"DBS backup"
    assert world["sent"]["taken"] == []
    assert world["env"].read_bytes() == TARGET_ENV
    assert target_versions(world) == []
    assert [run["argv"] for run in world["hosts"].runs(SOURCE)] == [["true"]]
    assert MIGRATE not in [run["argv"] for run in world["hosts"].runs(TARGET)]


@pytest.mark.django_db
def test_a_rehearsal_onto_an_unmigrated_target_checks_the_backup_here(
    api, world, run_jobs
):
    world["hosts"].answer(TARGET, MIGRATE_CHECK, (1, "", "unapplied"))
    real = stored_file(
        world["source"], "web-1-20261009-040000Z.dbs", dbs_backup(BACKUP_PASSPHRASE)
    )

    with run_jobs():
        response = api.post(REDEPLOY, body(world, backup=str(real.pk)), format="json")

    job = job_of(api, response)
    assert job["status"] == "succeeded"
    assert ("safety_backup", "skipped") in statuses(job)
    assert ("restore", "succeeded") in statuses(job)
    assert world["sent"]["restores"] == []
    restore = AuditEvent.objects.get(action="redeploy.restore")
    assert restore.data == {"validated": True, "target_not_migrated": True}


@pytest.mark.django_db
def test_a_rehearsal_without_a_kept_backup_says_so(api, world, run_jobs):
    BackupFileRepository().soft_delete(world["backup"])

    with run_jobs():
        response = api.post(REDEPLOY, body(world, backup=None), format="json")

    job = job_of(api, response)
    assert (job["status"], job["error_code"]) == ("failed", "no_backup_to_rehearse")
    assert job["detail"]["failed_step"] == "source_backup"


@pytest.mark.django_db
def test_a_move_backs_up_the_old_server_now_and_restores_that_backup(
    api, world, run_jobs
):
    job = moved(api, world, run_jobs)

    assert job["status"] == "succeeded", job
    assert statuses(job) == [(step, "succeeded") for step in STEPS]
    detail = job["detail"]
    assert detail["fresh_backup"] is True
    fresh = BackupFileRepository().find(detail["used_backup"])
    assert (fresh.server_id, fresh.kind) == (world["source"].pk, BackupFile.Kind.DBS)
    [restore] = world["sent"]["restores"]
    assert restore["data"] == stored_bytes(fresh.pk) != b"DBS backup"
    assert restore["stdin"] == BACKUP_PASSPHRASE
    assert "--dry-run" not in restore["argv"] and "--flush" not in restore["argv"]
    source_take = world["sent"]["taken"][0]
    assert (source_take["host"], source_take["passphrase"]) == (
        SOURCE,
        BACKUP_PASSPHRASE,
    )
    assert source_take["options"]["delete_remote"] is True
    assert world["hosts"].runs(SOURCE) == []
    assert world["env"].read_bytes() == ENV_CONTENT


@pytest.mark.django_db
def test_a_move_records_the_new_server_before_it_touches_it(api, world, run_jobs):
    job = moved(api, world, run_jobs)

    detail = job["detail"]
    recorded = EnvVersionRepository().find(detail["target_env_version"])
    assert unseal(recorded.content_sealed, context=env_contexts.CONTENT) == TARGET_ENV
    assert recorded.server_id == world["target"].pk
    safety = BackupFileRepository().find(detail["safety_backup"])
    assert (safety.server_id, safety.kind) == (world["target"].pk, BackupFile.Kind.DBS)
    target_take = world["sent"]["taken"][1]
    assert (target_take["host"], target_take["passphrase"]) == (
        TARGET,
        TARGET_PASSPHRASE,
    )
    assert world["sent"]["events"] == [
        f"backup {SOURCE}",
        f"backup {TARGET}",
        "migrate",
        "restore",
    ]


@pytest.mark.django_db
def test_a_move_never_unpacks_an_archive_on_the_new_server(api, world, run_jobs):
    moved(api, world, run_jobs, archives=[str(world["backup"].pk)])

    commands = [run["argv"][0] for run in world["hosts"].runs(TARGET)]
    assert "tar" not in commands


@pytest.mark.django_db
def test_an_old_server_that_cannot_be_reached_moves_the_chosen_backup(
    api, world, run_jobs
):
    world["hosts"].unreachable.add(SOURCE)

    job = moved(api, world, run_jobs)

    assert job["status"] == "succeeded", job
    detail = job["detail"]
    assert detail["fresh_backup"] is False
    assert detail["used_backup"] == str(world["backup"].pk)
    assert detail["source_error"] == "ssh_unreachable"
    [restore] = world["sent"]["restores"]
    assert restore["data"] == b"DBS backup"
    assert [take["host"] for take in world["sent"]["taken"]] == [TARGET]


@pytest.mark.django_db
def test_an_unreachable_old_server_without_a_backup_stops_before_the_new_one(
    api, world, run_jobs
):
    world["hosts"].unreachable.add(SOURCE)
    BackupFileRepository().soft_delete(world["backup"])

    job = moved(api, world, run_jobs, backup=None)

    assert (job["status"], job["error_code"]) == ("failed", "source_unreachable")
    assert job["detail"]["failed_step"] == "source_backup"
    assert job["detail"]["revertable"] is False
    assert world["sent"]["restores"] == []
    assert world["env"].read_bytes() == TARGET_ENV


@pytest.mark.django_db
def test_a_new_server_without_data_needs_no_safety_backup(api, world, run_jobs):
    world["hosts"].answer(TARGET, MIGRATE_CHECK, (1, "", "unapplied"))

    job = moved(api, world, run_jobs)

    assert job["status"] == "succeeded", job
    assert ("safety_backup", "skipped") in statuses(job)
    assert job["detail"]["target_had_data"] is False
    assert "safety_backup" not in job["detail"]
    assert [take["host"] for take in world["sent"]["taken"]] == [SOURCE]


@pytest.mark.django_db
def test_a_failing_step_stops_the_move_names_it_and_offers_the_revert(
    api, world, run_jobs
):
    failing_migration(world)

    job = moved(api, world, run_jobs)

    assert (job["status"], job["error_code"]) == ("failed", "remote_command_failed")
    assert statuses(job) == [
        ("check", "succeeded"),
        ("source_backup", "succeeded"),
        ("record_env", "succeeded"),
        ("safety_backup", "succeeded"),
        ("env", "succeeded"),
        ("migrate", "failed"),
        ("restore", "skipped"),
        ("final_check", "skipped"),
    ]
    assert job["detail"]["failed_step"] == "migrate"
    assert job["detail"]["revertable"] is True
    assert job["detail"]["output"] == "boom"
    assert world["sent"]["restores"] == []
    assert logged("redeploy.migrate")[0].status == "failed"


@pytest.mark.django_db
def test_a_move_that_stops_before_touching_the_new_server_offers_no_revert(
    api, world, run_jobs
):
    world["hosts"].answer(
        TARGET, [PYTHON, "manage.py", "dbs_backup", "--help"], (1, "", "no")
    )

    job = moved(api, world, run_jobs)

    assert (job["status"], job["error_code"]) == ("failed", "target_not_ready")
    assert job["detail"]["revertable"] is False


def revert(api, move, **fields):
    values = {"rehearsal": False, "password": PASSWORD, "confirm_name": "web-2"}
    return api.post(
        f"/api/redeploy/{move['id']}/revert/", {**values, **fields}, format="json"
    )


@pytest.mark.django_db
def test_a_revert_puts_the_recorded_env_and_data_back(api, world, run_jobs):
    failing_migration(world)
    move = moved(api, world, run_jobs)
    assert world["env"].read_bytes() == ENV_CONTENT

    with run_jobs():
        response = revert(api, move)
    job = job_of(api, response)

    assert (job["action"], job["status"]) == ("redeploy.revert", "succeeded"), job
    assert statuses(job) == [
        ("check", "succeeded"),
        ("env", "succeeded"),
        ("restore", "succeeded"),
    ]
    assert job["detail"]["move"] == move["id"]
    assert world["env"].read_bytes() == TARGET_ENV
    [restore] = world["sent"]["restores"]
    assert "--flush" in restore["argv"] and "--dry-run" not in restore["argv"]
    assert restore["stdin"] == TARGET_PASSPHRASE
    assert restore["data"] == stored_bytes(move["detail"]["safety_backup"])
    for step in ("check", "env", "restore"):
        assert logged(f"redeploy.revert_{step}")[0].subject == str(world["target"].pk)


@pytest.mark.django_db
def test_a_revert_rehearsal_changes_nothing(api, world, run_jobs):
    failing_migration(world)
    move = moved(api, world, run_jobs)

    with run_jobs():
        response = revert(api, move, rehearsal=True, password="")
    job = job_of(api, response)

    assert job["status"] == "succeeded", job
    assert statuses(job) == [
        ("check", "succeeded"),
        ("env", "skipped"),
        ("restore", "succeeded"),
    ]
    [restore] = world["sent"]["restores"]
    assert "--flush" in restore["argv"] and "--dry-run" in restore["argv"]
    assert world["env"].read_bytes() == ENV_CONTENT


@pytest.mark.django_db
def test_only_a_move_that_stopped_after_changing_the_new_server_can_be_reverted(
    api, world, run_jobs
):
    finished = moved(api, world, run_jobs)
    with run_jobs():
        response = api.post(REDEPLOY, body(world), format="json")
    rehearsed = job_of(api, response)

    for move in (finished, rehearsed):
        response = revert(api, move)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "move_not_revertable"
    assert api.post("/api/redeploy/999999/revert/", {}, format="json").status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("fields", "code"),
    [
        ({"confirm_name": "web-1"}, "confirm_name_mismatch"),
        ({"password": "wrong"}, "invalid_password"),
    ],
)
def test_a_revert_for_real_needs_the_name_and_the_password(
    api, world, run_jobs, fields, code
):
    failing_migration(world)
    move = moved(api, world, run_jobs)

    response = revert(api, move, **fields)

    assert response.json()["error"]["code"] == code
    assert logged("redeploy.revert_check") == []


@pytest.mark.django_db
def test_a_move_waits_for_a_job_already_running_on_the_old_server(
    api, world, run_jobs
):
    TakeLock().acquire(world["source"].pk, 424242)

    job = moved(api, world, run_jobs)

    assert (job["status"], job["error_code"]) == ("failed", "backup_running")
    assert job["detail"]["failed_step"] == "source_backup"
    assert world["sent"]["taken"] == []


@pytest.mark.django_db
def test_a_move_found_interrupted_lets_the_new_server_go(admin, world):
    job = JobQueue(admin).queue_backup(
        "redeploy.run",
        server=world["target"],
        target="web-2",
        send=lambda job: None,
        detail={"steps": []},
    )
    audit.interrupt()

    RedeployService().run(job.pk)

    assert TakeLock().holder(world["target"].pk) is None


@pytest.mark.django_db
def test_every_step_is_audited_against_the_target(api, world, run_jobs):
    with run_jobs():
        api.post(REDEPLOY, body(world), format="json")

    target = str(world["target"].pk)
    for step in ("check", "source_backup", "safety_backup", "restore"):
        [entry] = logged(f"redeploy.{step}")
        assert (entry.subject, entry.status) == (target, "succeeded")
    assert logged("redeploy.migrate") == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("fields", "code"),
    [
        (
            {"rehearsal": False, "password": PASSWORD, "confirm_name": "web-1"},
            "confirm_name_mismatch",
        ),
        (
            {"rehearsal": False, "password": "wrong", "confirm_name": "web-2"},
            "invalid_password",
        ),
    ],
)
def test_a_redeploy_for_real_needs_the_name_and_the_password(api, world, fields, code):
    response = api.post(REDEPLOY, body(world, **fields), format="json")

    assert response.json()["error"]["code"] == code
    assert logged("redeploy.check") == []


@pytest.mark.django_db
def test_a_refused_password_is_audited(api, world):
    api.post(
        REDEPLOY,
        body(world, rehearsal=False, password="wrong", confirm_name="web-2"),
        format="json",
    )

    [entry] = logged("redeploy.run")
    assert (entry.status, entry.error_code) == ("failed", "invalid_password")
    assert entry.subject == str(world["target"].pk)


@pytest.mark.django_db
def test_a_redeploy_for_real_without_a_password_names_the_field(api, world):
    response = api.post(
        REDEPLOY, body(world, rehearsal=False, confirm_name="web-2"), format="json"
    )

    assert response.json()["error"]["fields"] == {"password": ["required"]}


@pytest.mark.django_db
def test_the_source_and_target_must_differ(api, world):
    response = api.post(
        REDEPLOY, body(world, target_server=str(world["source"].pk)), format="json"
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "same_server"


@pytest.mark.django_db
def test_a_source_without_a_stored_passphrase_cannot_be_moved(api, world):
    ServerRepository().update(world["source"], backup_passphrase_sealed=None)

    response = api.post(REDEPLOY, body(world), format="json")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "passphrase_missing"


@pytest.mark.django_db
def test_files_must_belong_to_the_source(api, world, admin):
    other = stored_file(world["target"], "other.dbs", b"x")

    response = api.post(REDEPLOY, body(world, backup=str(other.pk)), format="json")

    assert response.json()["error"]["fields"] == {"backup": ["not_found"]}


@pytest.mark.django_db
def test_a_new_server_without_an_env_path_cannot_take_a_env(api, world):
    ServerRepository().update(world["target"], env_path="")

    response = api.post(
        REDEPLOY, body(world, env_version=str(world["version"].pk)), format="json"
    )

    assert response.json()["error"]["code"] == "env_path_missing"


@pytest.mark.django_db
def test_without_a_chosen_backup_the_newest_one_is_the_fallback(api, world, run_jobs):
    newest = stored_file(world["source"], "web-1-20261010-030000Z.dbs", b"newer")

    with run_jobs():
        response = api.post(REDEPLOY, body(world, backup=None), format="json")
    job = job_of(api, response)

    assert job["detail"]["backup"] == str(newest.pk)
    [restore] = world["sent"]["restores"]
    assert restore["data"] == b"newer"


@pytest.mark.django_db
def test_a_backup_restores_onto_another_server_with_its_own_passphrase(
    api, world, run_jobs
):
    with run_jobs():
        response = api.post(
            f"/api/backups/{world['backup'].pk}/restore/",
            {
                "mode": "merge",
                "rehearse": True,
                "target_server": str(world["target"].pk),
            },
            format="json",
        )

    job = job_of(api, response)
    assert job["status"] == "succeeded", job
    assert job["server"] == str(world["target"].pk)
    assert job["detail"]["target_server"] == str(world["target"].pk)
    [restore] = world["sent"]["restores"]
    assert restore["stdin"] == BACKUP_PASSPHRASE
    assert Path(restore["argv"][3]).name.startswith(".dbs-restore-")


@pytest.mark.django_db
def test_a_restore_for_real_onto_another_server_confirms_the_targets_name(api, world):
    response = api.post(
        f"/api/backups/{world['backup'].pk}/restore/",
        {
            "mode": "replace",
            "rehearse": False,
            "account_password": PASSWORD,
            "server_name": "web-1",
            "target_server": str(world["target"].pk),
        },
        format="json",
    )

    assert response.json()["error"]["fields"] == {"server_name": ["name_mismatch"]}


@pytest.mark.django_db
def test_a_restore_that_ran_out_of_time_blocks_a_retry_until_it_must_have_stopped(
    api, world, run_jobs, settings
):
    def too_slow(argv, stdin_line):
        raise RemoteTimeout("timed out")

    world["hosts"].answer(TARGET, [PYTHON, "manage.py", "dbs_restore"], too_slow)
    restore = {
        "mode": "merge",
        "rehearse": True,
        "target_server": str(world["target"].pk),
    }
    url = f"/api/backups/{world['backup'].pk}/restore/"
    before = timezone.now()

    with run_jobs():
        response = api.post(url, restore, format="json")

    job = job_of(api, response)
    assert (job["status"], job["error_code"]) == ("failed", "remote_command_timed_out")
    until = settling.settling_until(world["target"].pk)
    window = timedelta(
        seconds=settings.BACKUP_EXEC_TIMEOUT + settings.REMOTE_KILL_AFTER
    )
    assert before + window <= until <= timezone.now() + window
    retry = api.post(url, restore, format="json")
    assert (retry.status_code, retry.json()["error"]["code"]) == (409, "server_settling")


@pytest.mark.django_db
def test_a_server_that_has_timeout_stops_the_restore_itself(api, world, run_jobs):
    world["hosts"].answer(TARGET, ["true"], (0, "", ""))

    with run_jobs():
        response = api.post(REDEPLOY, body(world), format="json")

    assert job_of(api, response)["status"] == "succeeded"
    assert ServerRepository().get(world["target"].pk).timeout_on_host is True
    [restore] = [
        run["argv"] for run in world["hosts"].runs(TARGET) if "dbs_restore" in run["argv"]
    ]
    assert restore[:5] == ["timeout", "-k", "30", "3600", PYTHON]
    assert "--dry-run" in world["sent"]["restores"][0]["argv"]


@pytest.mark.django_db
def test_a_restore_without_the_sources_passphrase_is_refused(api, world):
    ServerRepository().update(world["source"], backup_passphrase_sealed=None)

    response = api.post(
        f"/api/backups/{world['backup'].pk}/restore/",
        {"mode": "merge", "rehearse": True, "target_server": str(world["target"].pk)},
        format="json",
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "passphrase_missing"
    assert json.dumps(response.json()).count("passphrase_missing") == 1
