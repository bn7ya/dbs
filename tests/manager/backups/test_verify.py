from __future__ import annotations

from uuid import uuid4

import pytest
from django.utils import timezone

from dbs import audit
from dbs.manager.backups.models import BackupFile
from dbs.manager.backups.repositories import BackupFileRepository
from dbs.manager.backups.services import BackupRunService, BackupService
from dbs.manager.backups.storage import BackupStorage
from tests.manager.backups.support import BackupHost
from tests.manager.servers.support import connecting_to, dbs_backup

CONNECT = "dbs.manager.servers.services.connection_service.connect"


def url(backup) -> str:
    return f"/api/backups/{backup.pk}/verify/"


def stored(backup) -> BackupFile:
    return BackupFileRepository().get(backup.pk)


@pytest.mark.django_db
def test_a_backup_that_decrypts_is_verified(api, admin, server, run_jobs, taken, entry):
    backup = taken()

    with run_jobs():
        response = api.post(url(backup))

    assert response.status_code == 202
    job = entry(response.json()["activity"])
    assert job.action == "backup.verify"
    assert job.status == audit.SUCCEEDED
    assert job.data == {"validation": "verified"}
    assert (job.subject, job.target_name, job.actor) == (
        str(server.pk),
        backup.name,
        admin,
    )
    assert stored(backup).validation == BackupFile.Validation.VERIFIED
    assert stored(backup).validated_at > backup.validated_at


@pytest.mark.django_db
def test_a_verify_answers_before_it_runs(api, taken, entry):
    backup = taken()

    job = entry(api.post(url(backup)).json()["activity"])

    assert job.status == audit.QUEUED
    assert stored(backup).validation == BackupFile.Validation.STRUCTURE_OK


@pytest.mark.django_db
@pytest.mark.parametrize(
    "content",
    [
        pytest.param(lambda: dbs_backup("another-passphrase"), id="another passphrase"),
        pytest.param(lambda: b"DBS but not really", id="not a backup"),
    ],
)
def test_a_backup_that_does_not_decrypt_is_a_result_not_an_error(
    api, admin, monkeypatch, server, run_jobs, taken, entry, content
):
    monkeypatch.setattr(CONNECT, connecting_to(BackupHost(content=content())))
    backup = taken()

    with run_jobs():
        job = entry(api.post(url(backup)).json()["activity"])

    job = entry(job.pk)
    assert job.status == audit.SUCCEEDED
    assert job.data == {"validation": "failed"}
    assert stored(backup).validation == BackupFile.Validation.FAILED


@pytest.mark.django_db
def test_a_file_that_left_the_disk_fails_the_job(api, run_jobs, taken, entry):
    backup = taken()
    BackupStorage().remove(backup.storage_path)

    with run_jobs():
        job = entry(api.post(url(backup)).json()["activity"])

    job = entry(job.pk)
    assert job.status == audit.FAILED
    assert job.error_code == "backup_missing"
    assert stored(backup).validation == BackupFile.Validation.STRUCTURE_OK


@pytest.mark.django_db
def test_a_deleted_or_unknown_backup_is_not_verified(api, taken):
    backup = taken()
    api.delete(f"/api/backups/{backup.pk}/")

    for backup_id in (backup.pk, uuid4()):
        response = api.post(f"/api/backups/{backup_id}/verify/")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"


@pytest.mark.django_db
def test_a_backup_deleted_after_its_verify_was_queued_is_still_verified(
    api, admin, django_capture_on_commit_callbacks, taken, entry
):
    backup = taken()
    with django_capture_on_commit_callbacks() as queued:
        job = BackupService(admin).verify(backup.pk)
    api.delete(f"/api/backups/{backup.pk}/")

    for send in queued:
        send()

    assert entry(job.pk).data == {"validation": "verified"}
    assert (
        BackupFileRepository().find_including_deleted(backup.pk).validation
        == "verified"
    )


@pytest.mark.django_db
def test_a_file_removed_after_its_verify_was_queued_fails_the_job(
    admin, django_capture_on_commit_callbacks, taken, entry
):
    backup = taken()
    with django_capture_on_commit_callbacks() as queued:
        job = BackupService(admin).verify(backup.pk)
    BackupFileRepository().update(backup, removed_at=timezone.now())

    for send in queued:
        send()

    assert entry(job.pk).error_code == "backup_missing"


@pytest.mark.django_db
def test_a_finished_verify_is_not_run_twice(admin, run_jobs, taken, entry):
    backup = taken()
    with run_jobs():
        job = BackupService(admin).verify(backup.pk)
    verified_at = stored(backup).validated_at

    BackupRunService().verify(job.pk, backup.pk)

    assert stored(backup).validated_at == verified_at
    assert entry(job.pk).status == audit.SUCCEEDED
