from __future__ import annotations

from uuid import uuid4

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from dbs import audit
from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.applications.services import ApplicationService
from dbs.manager.backups.locks import TakeLock
from dbs.manager.backups.repositories import BackupFileRepository
from dbs.manager.backups.services import BackupRunService, BackupService
from dbs.manager.backups.storage import BackupStorage
from dbs.manager.servers.exceptions import DbsTooOld, RestoreFailed
from dbs.manager.servers.gateways import RestoreReport
from tests.manager.backups.support import BackupHost
from tests.manager.factories import make_application
from tests.manager.servers.support import (
    BACKUP_DIR,
    BACKUP_PASSPHRASE,
    PASSWORD,
    PROJECT_DIR,
    PYTHON,
    SETTINGS_MODULE,
    body_line,
    connecting_to,
)

CONNECT = "dbs.manager.servers.services.connection_service.connect"
FOR_REAL = {"account_password": PASSWORD, "application_name": "web-1"}


def url(backup) -> str:
    return f"/api/backups/{backup.pk}/restore/"


def restore_entries(application):
    return list(
        ActivityRepository().filtered(
            subjects=[str(application.pk)], action="backup.restore"
        )
    )


@pytest.fixture
def other(admin, application):
    return make_application(
        admin,
        name="web-2",
        server=application.server,
        project_dir="/srv/other",
        python_path=PYTHON,
        remote_backup_dir="/var/backups/other",
        backup_passphrase="other-backup-passphrase",
    )


@pytest.mark.django_db
def test_a_rehearsal_needs_only_the_session_and_changes_nothing(
    api, admin, application, host, run_jobs, taken, entry, storage
):
    backup = taken()

    with run_jobs():
        response = api.post(
            url(backup), {"mode": "merge", "rehearse": True}, format="json"
        )

    assert response.status_code == 202
    job = entry(response.json()["activity"])
    assert job.action == "backup.restore"
    assert (job.subject, job.target_name, job.actor) == (
        str(application.pk),
        backup.name,
        admin,
    )
    assert job.status == audit.SUCCEEDED
    assert job.data == {
        "backup": str(backup.pk),
        "mode": "merge",
        "rehearse": True,
        "records": 42,
        "files": 3,
        "flushed": None,
        "healed": False,
    }
    [restore] = host.restores
    assert (restore.flush, restore.dry_run) == (False, True)
    assert restore.content == (storage / backup.storage_path).read_bytes()
    assert restore.passphrase == BACKUP_PASSPHRASE
    assert restore.remote_dir == BACKUP_DIR
    assert (restore.profile.python, restore.profile.project_dir) == (
        PYTHON,
        PROJECT_DIR,
    )
    assert restore.profile.settings_module == SETTINGS_MODULE


@pytest.mark.django_db
@pytest.mark.parametrize(("mode", "flush"), [("merge", False), ("replace", True)])
def test_a_restore_for_real_runs_with_the_password_and_the_name(
    api, host, run_jobs, taken, entry, mode, flush
):
    backup = taken()

    with run_jobs():
        response = api.post(
            url(backup), {"mode": mode, "rehearse": False, **FOR_REAL}, format="json"
        )

    assert response.status_code == 202
    job = entry(response.json()["activity"])
    assert job.status == audit.SUCCEEDED
    assert (job.data["mode"], job.data["rehearse"]) == (mode, False)
    [restore] = host.restores
    assert (restore.flush, restore.dry_run) == (flush, False)


@pytest.mark.django_db
def test_the_name_may_carry_spaces_around_it(api, host, run_jobs, taken):
    backup = taken()

    with run_jobs():
        response = api.post(
            url(backup),
            {
                "mode": "merge",
                "rehearse": False,
                **FOR_REAL,
                "application_name": "  web-1 ",
            },
            format="json",
        )

    assert response.status_code == 202
    assert len(host.restores) == 1


@pytest.mark.django_db
def test_a_restore_into_another_application_runs_there_with_the_backups_passphrase(
    api, application, other, host, run_jobs, taken, entry
):
    backup = taken()

    with run_jobs():
        response = api.post(
            url(backup),
            {"mode": "merge", "rehearse": True, "target_application": str(other.pk)},
            format="json",
        )

    assert response.status_code == 202
    job = entry(response.json()["activity"])
    assert job.status == audit.SUCCEEDED
    assert (job.subject, job.target_name) == (str(other.pk), backup.name)
    assert (job.data["source_application"], job.data["target_application"]) == (
        str(application.pk),
        str(other.pk),
    )
    [restore] = host.restores
    assert restore.passphrase == BACKUP_PASSPHRASE
    assert restore.remote_dir == "/var/backups/other"
    assert restore.profile.project_dir == "/srv/other"
    assert restore_entries(application) == []


@pytest.mark.django_db
def test_a_restore_for_real_into_another_application_needs_that_applications_name(
    api, other, host, run_jobs, taken
):
    backup = taken()
    body = {"mode": "merge", "rehearse": False, "target_application": str(other.pk)}

    with run_jobs():
        refused = api.post(url(backup), {**body, **FOR_REAL}, format="json")
        accepted = api.post(
            url(backup),
            {**body, **FOR_REAL, "application_name": "web-2"},
            format="json",
        )

    assert refused.status_code == 400
    assert refused.json()["error"]["fields"] == {"application_name": ["name_mismatch"]}
    assert accepted.status_code == 202
    assert len(host.restores) == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("sent", "fields"),
    [
        (
            {},
            {"account_password": ["required"], "application_name": ["name_mismatch"]},
        ),
        ({"application_name": "web-1"}, {"account_password": ["required"]}),
        ({"account_password": PASSWORD}, {"application_name": ["name_mismatch"]}),
        (
            {"account_password": PASSWORD, "application_name": "WEB-1"},
            {"application_name": ["name_mismatch"]},
        ),
    ],
)
def test_a_restore_for_real_without_both_writes_nothing(
    api, application, host, run_jobs, taken, sent, fields
):
    backup = taken()

    with run_jobs():
        response = api.post(
            url(backup), {"mode": "replace", "rehearse": False, **sent}, format="json"
        )

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid"
    assert error["fields"] == fields
    assert host.restores == []
    assert restore_entries(application) == []


@pytest.mark.django_db
def test_a_wrong_password_is_refused_and_logged(
    api, application, host, run_jobs, taken
):
    backup = taken()

    with run_jobs():
        response = api.post(
            url(backup),
            {
                **FOR_REAL,
                "mode": "replace",
                "rehearse": False,
                "account_password": "nope",
            },
            format="json",
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_password"
    assert host.restores == []
    [refused] = restore_entries(application)
    assert refused.status == audit.FAILED
    assert refused.error_code == "invalid_password"
    assert refused.target_name == backup.name
    assert refused.data == {
        "backup": str(backup.pk),
        "mode": "replace",
        "rehearse": False,
    }


@pytest.mark.django_db
def test_too_many_wrong_passwords_are_refused_whatever_the_next_one_is(
    api, settings, application, host, run_jobs, taken
):
    settings.AUTH_FAILURES_PER_USER = 2
    backup = taken()
    body = {**FOR_REAL, "mode": "merge", "rehearse": False}

    for _ in range(2):
        api.post(url(backup), {**body, "account_password": "nope"}, format="json")
    with run_jobs():
        response = api.post(url(backup), body, format="json")

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "too_many_attempts"
    assert host.restores == []
    assert [entry.error_code for entry in restore_entries(application)] == [
        "too_many_attempts",
        "invalid_password",
        "invalid_password",
    ]


@pytest.mark.django_db
def test_only_a_django_dbs_backup_restores(api, admin, application, host):
    uploaded = BackupService(admin).upload(
        application.pk, SimpleUploadedFile("db.sql", b"dump")
    )

    response = api.post(
        url(uploaded), {"mode": "merge", "rehearse": True}, format="json"
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "not_restorable"
    assert host.restores == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    "body",
    [
        {"rehearse": True},
        {"mode": "overwrite", "rehearse": True},
        {"mode": "merge"},
    ],
)
def test_a_body_without_a_mode_or_a_rehearse_is_refused(api, host, taken, body):
    backup = taken()

    response = api.post(url(backup), body, format="json")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid"
    assert host.restores == []


@pytest.mark.django_db
def test_a_deleted_backup_or_application_is_not_found(
    api, admin, application, host, taken
):
    backup = taken()
    other = taken()
    BackupService(admin).delete(backup.pk, account_password=PASSWORD)

    deleted_backup = api.post(
        url(backup), {"mode": "merge", "rehearse": True}, format="json"
    )
    ApplicationService(admin).delete(application.pk, account_password=PASSWORD)
    deleted_application = api.post(
        url(other), {"mode": "merge", "rehearse": True}, format="json"
    )

    assert deleted_backup.status_code == 404
    assert deleted_application.status_code == 404
    assert host.restores == []


@pytest.mark.django_db
def test_a_restore_and_a_backup_of_one_application_never_overlap(
    api, application, host, taken
):
    backup = taken()

    restore = api.post(url(backup), {"mode": "merge", "rehearse": True}, format="json")
    take = api.post("/api/backups/take/", {"application": application.pk})

    assert restore.status_code == 202
    assert take.status_code == 409
    assert take.json()["error"]["code"] == "backup_running"


@pytest.mark.django_db
def test_a_restore_is_refused_while_a_backup_of_the_application_is_queued(
    api, application, host, taken
):
    backup = taken()

    api.post("/api/backups/take/", {"application": application.pk})
    response = api.post(url(backup), {"mode": "merge", "rehearse": True}, format="json")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "backup_running"
    assert restore_entries(application) == []


@pytest.mark.django_db
def test_the_lock_is_let_go_when_the_restore_ends(
    api, application, host, run_jobs, taken
):
    backup = taken()

    with run_jobs():
        api.post(url(backup), {"mode": "merge", "rehearse": True}, format="json")
    with run_jobs():
        take = api.post("/api/backups/take/", {"application": application.pk})

    assert take.status_code == 202


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("failure", "code", "facts"),
    [
        (RestoreFailed(output="IntegrityError: duplicate key"), "restore_failed", {}),
        (
            DbsTooOld("0.2.2", output="error: unrecognized arguments: --dry-run"),
            "dbs_too_old",
            {"needs": "0.2.2"},
        ),
    ],
)
def test_a_restore_the_server_refuses_fails_the_job_with_its_output(
    api, monkeypatch, run_jobs, taken, entry, failure, code, facts
):
    backup = taken()
    monkeypatch.setattr(CONNECT, connecting_to(BackupHost(failure=failure)))

    with run_jobs():
        job = entry(
            api.post(
                url(backup), {"mode": "merge", "rehearse": True}, format="json"
            ).json()["activity"]
        )

    job = entry(job.pk)
    assert job.status == audit.FAILED
    assert job.error_code == code
    assert job.data == {
        "backup": str(backup.pk),
        "mode": "merge",
        "rehearse": True,
        "output": failure.output,
        **facts,
    }


@pytest.mark.django_db
def test_a_job_that_finds_another_backup_running_fails_with_backup_running(
    admin, application, host, django_capture_on_commit_callbacks, taken, entry
):
    backup = taken()
    with django_capture_on_commit_callbacks() as queued:
        job = BackupService(admin).restore(backup.pk, mode="merge", rehearse=True)
    locks = TakeLock()
    locks.release(application.pk, job.pk)
    other = uuid4()
    locks.acquire(application.pk, other)

    for send in queued:
        send()

    assert entry(job.pk).error_code == "backup_running"
    assert host.restores == []
    assert locks.hold(application.pk, other)


@pytest.mark.django_db
def test_a_file_removed_after_its_restore_was_queued_fails_the_job(
    admin, host, django_capture_on_commit_callbacks, taken, entry
):
    backup = taken()
    with django_capture_on_commit_callbacks() as queued:
        job = BackupService(admin).restore(backup.pk, mode="merge", rehearse=True)
    BackupFileRepository().update(backup, removed_at=timezone.now())

    for send in queued:
        send()

    assert entry(job.pk).error_code == "backup_missing"
    assert host.restores == []


@pytest.mark.django_db
def test_a_finished_restore_is_not_run_twice(admin, host, run_jobs, taken, entry):
    backup = taken()
    with run_jobs():
        job = BackupService(admin).restore(backup.pk, mode="merge", rehearse=True)

    BackupRunService().restore(job.pk, backup.pk)

    assert len(host.restores) == 1
    assert entry(job.pk).status == audit.SUCCEEDED


@pytest.mark.django_db
def test_a_copy_that_could_not_be_removed_is_named(
    api, monkeypatch, run_jobs, taken, entry
):
    backup = taken()
    left = f"{BACKUP_DIR}/.dbs-restore-0123456789abcdef.dbs"
    report = RestoreReport(records=1, files=0, flushed=5, healed=True, copy_left=left)
    monkeypatch.setattr(CONNECT, connecting_to(BackupHost(restored=report)))

    with run_jobs():
        job = entry(
            api.post(
                url(backup), {"mode": "replace", "rehearse": True}, format="json"
            ).json()["activity"]
        )

    job = entry(job.pk)
    assert job.status == audit.SUCCEEDED
    assert job.data["copy_left"] == left
    assert (job.data["flushed"], job.data["healed"]) == (5, True)


@pytest.mark.django_db
def test_a_file_that_left_the_disk_fails_the_job(api, host, run_jobs, taken, entry):
    backup = taken()
    BackupStorage().remove(backup.storage_path)

    with run_jobs():
        job = entry(
            api.post(
                url(backup), {"mode": "merge", "rehearse": True}, format="json"
            ).json()["activity"]
        )

    job = entry(job.pk)
    assert job.status == audit.FAILED
    assert job.error_code == "backup_missing"
    assert host.restores == []


@pytest.mark.django_db
def test_a_backup_deleted_after_it_was_queued_is_still_restored(
    api, admin, host, run_jobs, taken, entry
):
    backup = taken()

    with run_jobs():
        job = api.post(url(backup), {"mode": "merge", "rehearse": True}, format="json")
        BackupService(admin).delete(backup.pk, account_password=PASSWORD)

    assert entry(job.json()["activity"]).status == audit.SUCCEEDED
    assert BackupFileRepository().find(backup.pk) is None


@pytest.mark.django_db
def test_a_restore_holds_no_secret_in_the_log(
    api, application, host, private_key, run_jobs, taken
):
    backup = taken()

    with run_jobs():
        api.post(
            url(backup), {"mode": "merge", "rehearse": False, **FOR_REAL}, format="json"
        )
    api.post(
        url(backup),
        {"mode": "merge", "rehearse": False, **FOR_REAL, "account_password": "nope"},
        format="json",
    )

    body = api.get(
        "/api/activity/", {"server": application.server_id, "page_size": 200}
    ).content.decode()
    for secret in (BACKUP_PASSPHRASE, body_line(private_key), PASSWORD, "nope"):
        assert secret not in body


@pytest.mark.django_db
def test_a_restore_needs_a_session(anonymous, taken):
    backup = taken()

    response = anonymous.post(
        url(backup), {"mode": "merge", "rehearse": True}, format="json"
    )

    assert response.status_code == 403
