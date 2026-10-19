from __future__ import annotations

from uuid import uuid4

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from dbs import audit
from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.applications.services import ApplicationService
from dbs.manager.backups.services import BackupService
from dbs.manager.backups.storage import BackupStorage
from tests.manager.factories import make_application
from tests.manager.support import PASSWORD

LIST = "/api/backups/"

SHAPE = {
    "id",
    "application",
    "application_name",
    "server",
    "server_name",
    "kind",
    "name",
    "size",
    "sha256",
    "validation",
    "validated_at",
    "failure",
    "remote_path",
    "taken_by",
    "plan",
    "plan_name",
    "created_at",
}


def url(backup, action: str = "") -> str:
    return f"{LIST}{backup.pk}/{action}"


def logged(action: str):
    return list(ActivityRepository().filtered(action=action))


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", ""),
        ("post", "take/"),
        ("post", "upload/"),
        ("delete", "{id}/"),
        ("get", "{id}/download/"),
        ("post", "{id}/verify/"),
        ("post", "{id}/undo-delete/"),
    ],
)
def test_every_endpoint_needs_a_session(anonymous, method, path):
    response = getattr(anonymous, method)(LIST + path.format(id=uuid4()))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_authenticated"


@pytest.mark.django_db
def test_the_list_refuses_an_application_that_is_not_an_id(api):
    malformed = api.get(LIST, {"application": "web-1"})

    assert malformed.status_code == 400
    assert malformed.json()["error"]["code"] == "invalid"
    assert malformed.json()["error"]["fields"] == {"application": ["invalid"]}


@pytest.mark.django_db
def test_the_list_without_an_application_holds_every_live_applications_backups(
    api, admin, application, taken
):
    backup = taken()
    other = make_application(admin, name="web-2", server=application.server)
    uploaded = BackupService(admin).upload(
        other.pk, SimpleUploadedFile("db.sql", b"dump")
    )
    gone = make_application(admin, name="web-3", server=application.server)
    BackupService(admin).upload(gone.pk, SimpleUploadedFile("old.sql", b"old"))
    ApplicationService(admin).delete(gone.pk, account_password=PASSWORD)

    body = api.get(LIST).json()

    assert body["count"] == 2
    assert [row["id"] for row in body["results"]] == [str(uploaded.pk), str(backup.pk)]
    assert [row["application_name"] for row in body["results"]] == ["web-2", "web-1"]


@pytest.mark.django_db
def test_a_backup_has_the_documented_shape(api, application, taken):
    backup = taken()

    body = api.get(LIST, {"application": application.pk}).json()

    assert (body["count"], body["next"], body["previous"]) == (1, None, None)
    [row] = body["results"]
    assert set(row) == SHAPE
    assert row["id"] == str(backup.pk)
    assert (row["application"], row["application_name"]) == (
        str(application.pk),
        "web-1",
    )
    assert (row["server"], row["server_name"]) == (
        str(application.server_id),
        application.server.name,
    )
    assert row["kind"] == "dbs"
    assert row["name"] == backup.name
    assert row["size"] == backup.size
    assert row["sha256"] == backup.sha256
    assert row["validation"] == "verified"
    assert row["failure"] == ""
    assert row["validated_at"] is not None
    assert row["remote_path"] == backup.remote_path
    assert row["taken_by"] == "sara"
    assert (row["plan"], row["plan_name"]) == (None, None)
    assert str(backup) == backup.name


@pytest.mark.django_db
def test_the_list_is_newest_first_and_paginated(api, application, taken):
    oldest, middle, newest = taken(), taken(), taken()

    first = api.get(LIST, {"application": application.pk, "page_size": 2}).json()
    second = api.get(
        LIST, {"application": application.pk, "page_size": 2, "page": 2}
    ).json()

    assert first["count"] == 3
    assert [row["id"] for row in first["results"]] == [str(newest.pk), str(middle.pk)]
    assert [row["id"] for row in second["results"]] == [str(oldest.pk)]


@pytest.mark.django_db
def test_the_list_holds_only_that_applications_backups_that_are_not_deleted(
    api, admin, application, taken
):
    kept, deleted = taken(), taken()
    api.delete(url(deleted), {"account_password": PASSWORD}, format="json")
    other = make_application(admin, name="web-2", server=application.server)
    BackupService(admin).upload(other.pk, SimpleUploadedFile("db.sql", b"dump"))

    listed = api.get(LIST, {"application": application.pk}).json()["results"]
    ids = [row["id"] for row in listed]

    assert ids == [str(kept.pk)]
    assert api.get(LIST, {"application": uuid4()}).json()["count"] == 0


@pytest.mark.django_db
def test_a_deleted_applications_backups_are_still_listed_under_it(
    api, admin, application, taken
):
    backup = taken()
    ApplicationService(admin).delete(application.pk, account_password=PASSWORD)

    listed = api.get(LIST, {"application": application.pk}).json()["results"]
    ids = [row["id"] for row in listed]

    assert ids == [str(backup.pk)]


@pytest.mark.django_db
def test_one_backup_is_read_from_the_list_not_on_its_own(api, taken):
    assert api.get(url(taken())).status_code == 405


@pytest.mark.django_db
def test_a_download_is_the_stored_file_as_an_attachment(
    api, admin, application, storage, taken
):
    backup = taken()

    response = api.get(url(backup, "download/"))

    assert response.status_code == 200
    assert (
        b"".join(response.streaming_content)
        == (storage / backup.storage_path).read_bytes()
    )
    assert response["Content-Type"] == "application/octet-stream"
    assert response["Content-Disposition"] == f'attachment; filename="{backup.name}"'
    assert response["Content-Length"] == str(backup.size)
    assert response["Cache-Control"] == "no-store"
    [entry] = logged("backup.download")
    assert entry.status == audit.SUCCEEDED
    assert entry.subject == str(application.pk)
    assert entry.target_name == backup.name
    assert entry.actor == admin


@pytest.mark.django_db
def test_a_file_that_left_the_disk_is_missing(api, taken):
    backup = taken()
    BackupStorage().remove(backup.storage_path)

    response = api.get(url(backup, "download/"))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "backup_missing"
    assert logged("backup.download") == []


@pytest.mark.django_db
def test_a_deleted_backup_is_not_downloaded(api, taken):
    backup = taken()
    api.delete(url(backup), {"account_password": PASSWORD}, format="json")

    response = api.get(url(backup, "download/"))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.django_db
def test_a_deleted_backup_is_hidden_and_its_file_kept(
    api, admin, application, storage, taken
):
    backup = taken()

    response = api.delete(url(backup), {"account_password": PASSWORD}, format="json")

    assert response.status_code == 204
    assert api.get(LIST, {"application": application.pk}).json()["count"] == 0
    assert (storage / backup.storage_path).is_file()
    [entry] = logged("backup.delete")
    assert (entry.subject, entry.target_name, entry.actor) == (
        str(application.pk),
        backup.name,
        admin,
    )
    for backup_id in (backup.pk, uuid4()):
        again = api.delete(
            f"{LIST}{backup_id}/", {"account_password": PASSWORD}, format="json"
        )
        assert again.status_code == 404
        assert again.json()["error"]["code"] == "not_found"


@pytest.mark.django_db
def test_a_delete_can_be_undone_while_the_file_is_on_disk(
    api, admin, application, taken
):
    backup = taken()
    [listed] = api.get(LIST, {"application": application.pk}).json()["results"]
    api.delete(url(backup), {"account_password": PASSWORD}, format="json")

    response = api.post(url(backup, "undo-delete/"))

    assert response.status_code == 200
    assert response.json() == listed
    assert api.get(LIST, {"application": application.pk}).json()["count"] == 1
    [entry] = logged("backup.undo_delete")
    assert (entry.subject, entry.target_name, entry.actor) == (
        str(application.pk),
        backup.name,
        admin,
    )


@pytest.mark.django_db
def test_only_a_deleted_backup_with_its_file_can_be_brought_back(api, taken):
    alive, gone = taken(), taken()
    api.delete(url(gone))
    BackupStorage().remove(gone.storage_path)

    for backup_url in (url(alive, "undo-delete/"), url(gone, "undo-delete/")):
        response = api.post(backup_url)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
    assert api.post(f"{LIST}{uuid4()}/undo-delete/").status_code == 404
    assert logged("backup.undo_delete") == []
