from __future__ import annotations

import hashlib
import stat
from uuid import uuid4

import pytest

from dbs import audit
from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.backups.locks import TakeLock
from dbs.manager.backups.models import BackupFile
from dbs.manager.backups.repositories import BackupFileRepository
from dbs.manager.backups.services import BackupRunService, BackupService
from dbs.manager.servers.exceptions import (
    BackupInvalid,
    HostKeyChanged,
    RemoteCommandFailed,
    SSHAuthFailed,
    SSHUnreachable,
)
from dbs.manager.servers.gateways import DbsProfile
from dbs.manager.servers.services import ServerService
from tests.manager.backups.support import BackupHost
from tests.manager.servers.support import (
    BACKUP_DIR,
    BACKUP_PASSPHRASE,
    PASSWORD,
    PROJECT_DIR,
    PYTHON,
    SETTINGS_MODULE,
    connecting_to,
    refusing_with,
)

TAKE = "/api/backups/take/"
CONNECT = "dbs.manager.servers.services.connection_service.connect"


def mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def files_on_disk(root) -> list:
    return [path for path in root.rglob("*") if path.is_file()] if root.exists() else []


def takes():
    return list(ActivityRepository().filtered(action="backup.take"))


@pytest.mark.django_db
def test_a_take_answers_at_once_with_the_job_to_watch(api, admin, server, host, entry):
    response = api.post(TAKE, {"server": server.pk})

    assert response.status_code == 202
    assert set(response.json()) == {"activity"}
    job = entry(response.json()["activity"])
    assert job.action == "backup.take"
    assert job.status == audit.QUEUED
    assert job.subject == str(server.pk)
    assert job.target_name == "web-1"
    assert job.actor == admin
    assert job.remote_addr == "127.0.0.1"
    assert job.started_at is None
    assert host.takes == []


@pytest.mark.django_db
def test_a_take_needs_a_server(api):
    missing = api.post(TAKE, {})
    malformed = api.post(TAKE, {"server": "web-1"})

    assert missing.status_code == malformed.status_code == 400
    assert missing.json()["error"] == {
        "code": "invalid",
        "message": "This field is required.",
        "fields": {"server": ["required"]},
    }
    assert malformed.json()["error"]["fields"] == {"server": ["invalid"]}
    assert takes() == []


@pytest.mark.django_db
def test_an_unknown_or_deleted_server_is_not_found(api, admin, server):
    ServerService(admin).delete(server.pk)

    for server_id in (server.pk, uuid4()):
        response = api.post(TAKE, {"server": server_id})
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
    assert takes() == []


@pytest.mark.django_db
def test_a_taken_backup_is_stored_and_described(
    api, admin, server, host, run_jobs, storage, entry
):
    with run_jobs():
        response = api.post(TAKE, {"server": server.pk})

    job = entry(response.json()["activity"])
    assert job.status == audit.SUCCEEDED
    assert job.error_code == ""
    assert job.finished_at >= job.started_at
    backup = BackupFileRepository().get(job.data["backup"])
    assert job.data == {"backup": str(backup.pk), "size": backup.size}

    path = storage / str(server.pk) / backup.name
    assert path.stat().st_size == backup.size
    assert backup.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert backup.storage_path == f"{server.pk}/{backup.name}"
    assert backup.name.startswith("web-1-") and backup.name.endswith(".dbs")
    assert backup.server_id == server.pk
    assert backup.kind == BackupFile.Kind.DBS
    assert backup.validation == BackupFile.Validation.STRUCTURE_OK
    assert backup.validated_at is not None
    assert backup.remote_path == f"{BACKUP_DIR}/{backup.name}"
    assert backup.created_by == admin
    assert backup.sealed is False

    assert mode(path) == 0o600
    assert mode(path.parent) == 0o700
    assert mode(storage) == 0o700


@pytest.mark.django_db
def test_the_server_is_asked_for_its_own_backup(admin, server, host, run_jobs, storage):
    with run_jobs():
        BackupService(admin).take(server.pk)

    [take] = host.takes
    assert take.profile == DbsProfile(
        python=PYTHON,
        manage="manage.py",
        project_dir=PROJECT_DIR,
        settings_module=SETTINGS_MODULE,
    )
    assert take.passphrase == BACKUP_PASSPHRASE
    assert take.dest_dir == str(storage / str(server.pk))
    assert take.prefix == "web-1"
    assert take.keep_remote == 1
    assert host.credentials.host == "10.0.0.5"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("name", "prefix"), [("Web Server 2", "web-server-2"), ("خادم", "backup")]
)
def test_file_names_start_with_the_server_name_or_backup(
    admin, server, host, run_jobs, name, prefix
):
    ServerService(admin).update(server.pk, account_password=PASSWORD, name=name)

    with run_jobs():
        BackupService(admin).take(server.pk)

    assert host.takes[0].prefix == prefix


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("error", "code"),
    [
        (HostKeyChanged(), "host_key_changed"),
        (SSHAuthFailed(), "ssh_auth_failed"),
        (SSHUnreachable(), "ssh_unreachable"),
    ],
)
def test_a_server_that_cannot_be_reached_fails_the_job(
    admin, monkeypatch, server, run_jobs, storage, entry, error, code
):
    monkeypatch.setattr(CONNECT, refusing_with(error))

    with run_jobs():
        job = BackupService(admin).take(server.pk)

    failed = entry(job.pk)
    assert failed.status == audit.FAILED
    assert failed.error_code == code
    assert failed.data == {}
    assert list(BackupFileRepository().alive_for_server(server.pk)) == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("error", "code"),
    [
        (
            RemoteCommandFailed(output="exit 1: No module named dbs"),
            "remote_command_failed",
        ),
        (BackupInvalid(output="[INVALID] Not a DBS container"), "backup_invalid"),
    ],
)
def test_a_take_the_server_fails_keeps_the_end_of_its_output(
    admin, monkeypatch, server, run_jobs, storage, entry, error, code
):
    monkeypatch.setattr(CONNECT, connecting_to(BackupHost(failure=error)))

    with run_jobs():
        job = BackupService(admin).take(server.pk)

    failed = entry(job.pk)
    assert failed.status == audit.FAILED
    assert failed.error_code == code
    assert failed.data == {"output": error.output}
    assert list(BackupFileRepository().alive_for_server(server.pk)) == []
    assert files_on_disk(storage) == []


@pytest.mark.django_db
def test_a_remote_failure_with_nothing_printed_has_no_output(
    admin, monkeypatch, server, run_jobs, entry
):
    monkeypatch.setattr(
        CONNECT, connecting_to(BackupHost(failure=RemoteCommandFailed()))
    )

    with run_jobs():
        job = BackupService(admin).take(server.pk)

    assert entry(job.pk).data == {}


@pytest.mark.django_db
def test_a_server_deleted_before_the_job_runs_fails_it(
    admin, server, host, django_capture_on_commit_callbacks, entry
):
    with django_capture_on_commit_callbacks() as queued:
        job = BackupService(admin).take(server.pk)
    ServerService(admin).delete(server.pk)

    for send in queued:
        send()

    assert entry(job.pk).error_code == "not_found"
    assert host.takes == []


@pytest.mark.django_db
def test_a_file_that_cannot_be_recorded_does_not_stay_on_disk(
    admin, monkeypatch, server, host, run_jobs, storage
):
    def refuse(*args, **kwargs):
        raise RuntimeError("database went away")

    monkeypatch.setattr(BackupFileRepository, "create", refuse)

    with pytest.raises(RuntimeError), run_jobs():
        BackupService(admin).take(server.pk)

    [failed] = takes()
    assert failed.status == audit.FAILED
    assert failed.error_code == "unexpected"
    assert files_on_disk(storage) == []
    assert TakeLock().acquire(server.pk, uuid4())


@pytest.mark.django_db
def test_a_second_take_of_a_server_is_refused_while_one_is_queued(
    api, server, host, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks():
        first = api.post(TAKE, {"server": server.pk})
        second = api.post(TAKE, {"server": server.pk})

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "backup_running"
    assert [job.status for job in takes()] == [audit.QUEUED]


@pytest.mark.django_db
@pytest.mark.parametrize("failure", [None, SSHUnreachable()])
def test_a_server_can_be_taken_again_once_a_take_ends(
    admin, monkeypatch, server, run_jobs, entry, failure
):
    monkeypatch.setattr(CONNECT, connecting_to(BackupHost(failure=failure)))
    service = BackupService(admin)

    with run_jobs():
        service.take(server.pk)
    with run_jobs():
        again = service.take(server.pk)

    assert entry(again.pk).status != audit.QUEUED
    assert len(takes()) == 2


@pytest.mark.django_db
def test_other_servers_are_not_held_up(
    admin, server, host, django_capture_on_commit_callbacks
):
    other = ServerService(admin).create(
        name="web-2",
        host="10.0.0.6",
        username="deploy",
        auth_method="password",
        password="ssh-password",
        host_key=server.host_key,
    )

    with django_capture_on_commit_callbacks():
        BackupService(admin).take(server.pk)
        BackupService(admin).take(other.pk)

    assert len(takes()) == 2


@pytest.mark.django_db
def test_a_job_that_finds_another_take_running_fails_with_backup_running(
    admin, server, host, django_capture_on_commit_callbacks, entry
):
    with django_capture_on_commit_callbacks() as queued:
        job = BackupService(admin).take(server.pk)
    locks = TakeLock()
    locks.release(server.pk, job.pk)
    other = uuid4()
    locks.acquire(server.pk, other)

    for send in queued:
        send()

    assert entry(job.pk).error_code == "backup_running"
    assert host.takes == []
    assert not locks.acquire(server.pk, uuid4())
    assert locks.hold(server.pk, other)


@pytest.mark.django_db
def test_a_finished_job_is_not_run_twice(admin, server, host, run_jobs, entry):
    with run_jobs():
        job = BackupService(admin).take(server.pk)

    BackupRunService().take(job.pk)

    assert len(host.takes) == 1
    assert entry(job.pk).status == audit.SUCCEEDED


@pytest.mark.django_db
def test_a_job_the_broker_refuses_fails_and_lets_the_server_go(
    admin, monkeypatch, server, host, run_jobs, entry
):
    def unreachable(*args):
        raise RuntimeError("cannot schedule new futures after shutdown")

    monkeypatch.setattr("dbs.manager.runner.JobRunner.submit", unreachable)

    with pytest.raises(RuntimeError), run_jobs():
        BackupService(admin).take(server.pk)

    [job] = takes()
    assert job.status == audit.FAILED
    assert job.error_code == "unexpected"
    assert TakeLock().acquire(server.pk, uuid4())
