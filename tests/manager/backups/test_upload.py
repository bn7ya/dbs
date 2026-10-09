from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path
from uuid import uuid4

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http.request import RawPostDataException
from rest_framework.test import APIClient

from dbs import audit
from dbs.manager import vault
from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.activity.services import ActivityService
from dbs.manager.backups.repositories import BackupFileRepository
from dbs.manager.backups.services import BackupService, backup_service
from dbs.manager.backups.uploads import UploadHandler
from dbs.manager.common.uploads import FORM_ALLOWANCE, UploadTooLarge
from dbs.manager.servers.services import ServerService

URL = "/api/backups/upload/"
BOUNDARY = "dbs-manager-upload-boundary"
CONTENT = b"-- PostgreSQL database dump\nCOPY accounts (email) FROM stdin;\nsara@example.com\n"
CSRF_TOKEN = "a" * 32
SHAPE = {
    "id",
    "server",
    "server_name",
    "kind",
    "name",
    "size",
    "sha256",
    "validation",
    "validated_at",
    "remote_path",
    "taken_by",
    "plan",
    "plan_name",
    "created_at",
}


def form(*, server=None, name: str | None = None, content: bytes = CONTENT) -> bytes:
    parts = []
    if server is not None:
        parts.append(
            f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="server"\r\n\r\n'
            f"{server}\r\n".encode()
        )
    if name is not None:
        parts.append(
            f"--{BOUNDARY}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{name}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n".encode()
            + content
            + b"\r\n"
        )
    parts.append(f"--{BOUNDARY}--\r\n".encode())
    return b"".join(parts)


def post(client: APIClient, body: bytes, **extra):
    return client.generic(
        "POST",
        URL,
        body,
        content_type=f"multipart/form-data; boundary={BOUNDARY}",
        **extra,
    )


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def waiting(storage: Path) -> list[Path]:
    uploads = storage / ".uploads"
    return sorted(uploads.iterdir()) if uploads.exists() else []


def stored(storage: Path, server) -> list[str]:
    directory = storage / str(server.pk)
    return (
        sorted(path.name for path in directory.iterdir()) if directory.exists() else []
    )


def logged(action: str):
    return list(ActivityRepository().filtered(action=action))


@pytest.fixture
def send(api, server):

    def send(
        name: str | None = "db.sql.gz", content: bytes = CONTENT, *, to=None, **extra
    ):
        body = form(server=server.pk if to is None else to, name=name, content=content)
        return post(extra.pop("client", api), body, **extra)

    return send


@pytest.mark.django_db
def test_an_upload_is_kept_sealed_and_answered_as_a_backup(
    api, admin, server, storage, send
):
    response = send()

    assert response.status_code == 201
    body = response.json()
    assert set(body) == SHAPE
    assert body["server"] == str(server.pk)
    assert (body["kind"], body["name"]) == ("uploaded", "db.sql.gz")
    assert (body["size"], body["sha256"]) == (
        len(CONTENT),
        hashlib.sha256(CONTENT).hexdigest(),
    )
    assert body["validation"] == "structure_ok"
    assert body["validated_at"] is not None
    assert body["remote_path"] == ""
    assert body["taken_by"] == "sara"
    assert (body["plan"], body["plan_name"]) == (None, None)
    row = BackupFileRepository().get(body["id"])
    assert (row.sealed, row.created_by, row.server) == (True, admin, server)
    assert row.storage_path == f"{server.pk}/db.sql.gz.sealed"
    sealed = storage / row.storage_path
    assert mode(sealed) == 0o600
    assert b"PostgreSQL" not in sealed.read_bytes()
    assert stored(storage, server) == ["db.sql.gz.sealed"]
    assert waiting(storage) == []
    [listed] = api.get("/api/backups/", {"server": server.pk}).json()["results"]
    assert listed == body


@pytest.mark.django_db
def test_an_upload_downloads_as_it_was_sent(monkeypatch, api, send):
    monkeypatch.setattr(vault, "CHUNK_BYTES", 8)
    backup = send().json()

    response = api.get(f"/api/backups/{backup['id']}/download/")

    assert b"".join(response.streaming_content) == CONTENT
    assert response["Content-Disposition"] == 'attachment; filename="db.sql.gz"'
    assert response["Content-Length"] == str(len(CONTENT))


@pytest.mark.django_db
def test_an_upload_is_verified_deleted_and_brought_back_like_any_backup(
    api, run_jobs, entry, storage, send
):
    backup = send().json()

    with run_jobs():
        verified = api.post(f"/api/backups/{backup['id']}/verify/")
    deleted = api.delete(f"/api/backups/{backup['id']}/")
    restored = api.post(f"/api/backups/{backup['id']}/undo-delete/")

    job = entry(verified.json()["activity"])
    assert (job.status, job.data) == (
        audit.SUCCEEDED,
        {"validation": "verified"},
    )
    assert deleted.status_code == 204
    assert restored.status_code == 200
    assert restored.json()["validation"] == "verified"


@pytest.mark.django_db
def test_an_upload_is_logged_with_its_name_and_size(admin, server, send):
    send(name="nightly.dump")

    [upload] = logged("backup.upload")
    assert (upload.status, upload.actor, upload.subject) == (
        audit.SUCCEEDED,
        admin,
        str(server.pk),
    )
    assert (upload.target_name, upload.data) == ("nightly.dump", {"size": len(CONTENT)})


@pytest.mark.django_db
def test_the_file_waits_in_a_private_file_on_the_backup_volume_until_it_is_sealed(
    monkeypatch, storage, send
):
    seen = []
    seal_stream = backup_service.seal_stream

    def watching(source, target, *, context):
        path = Path(source.file.name)
        seen.append((path, mode(path), mode(path.parent), path.read_bytes()))
        return seal_stream(source, target, context=context)

    monkeypatch.setattr(backup_service, "seal_stream", watching)

    assert send().status_code == 201

    [(path, file_mode, directory_mode, content)] = seen
    assert path.parent == storage / ".uploads"
    assert (file_mode, directory_mode, content) == (0o600, 0o700, CONTENT)
    assert not path.exists()


@pytest.mark.django_db
def test_only_the_upload_handler_reads_the_body_even_when_the_csrf_check_reads_it_first(
    settings, admin, storage, send
):
    settings.FILE_UPLOAD_HANDLERS = []
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(admin)
    client.cookies[settings.CSRF_COOKIE_NAME] = CSRF_TOKEN

    refused = send(client=client)
    kept = send(client=client, HTTP_X_CSRFTOKEN=CSRF_TOKEN)
    settings.BACKUP_UPLOAD_MAX_BYTES = len(CONTENT) - 1
    too_large = send(client=client, HTTP_X_CSRFTOKEN=CSRF_TOKEN)

    assert refused.status_code == 403
    assert kept.status_code == 201
    assert kept.json()["size"] == len(CONTENT)
    assert too_large.status_code == 413
    assert too_large.json()["error"]["code"] == "upload_too_large"
    assert waiting(storage) == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("sent", "kept"),
    [
        ("../../etc/db.sql.gz", "db.sql.gz"),
        ("C:\\Users\\sara\\Backups\\db.sql.gz", "db.sql.gz"),
        ("db\x01\x1b-\x7f1.sql.gz", "db-1.sql.gz"),
        ("\u202egpj.sql.gz", "gpj.sql.gz"),
        ("  نسخة الليل.sql.gz  ", "نسخة الليل.sql.gz"),
        ("a" * 300 + ".sql.gz", "a" * 252 + ".gz"),
    ],
    ids=[
        "folders",
        "windows-path",
        "control-characters",
        "rtl-override",
        "arabic",
        "long",
    ],
)
def test_a_backup_is_named_after_the_file_without_its_folders_or_unprintable_characters(
    api, server, send, sent, kept
):
    response = send(name=sent)

    assert response.status_code == 201
    assert response.json()["name"] == kept
    download = api.get(f"/api/backups/{response.json()['id']}/download/")
    assert download["Content-Disposition"].startswith("attachment; filename")


@pytest.mark.django_db
@pytest.mark.parametrize("sent", ["   ", " .. ", ". "])
def test_a_name_that_is_only_spaces_or_dots_is_refused(server, storage, send, sent):
    response = send(name=sent)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid"
    assert response.json()["error"]["fields"] == {"file": ["invalid_name"]}
    assert stored(storage, server) == []
    assert waiting(storage) == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("sent", "code"),
    [
        ("", "invalid"),
        (".", "required"),
        ("../", "required"),
        ("backups/..", "required"),
    ],
)
def test_a_file_with_no_name_at_all_is_not_a_file(send, sent, code):
    response = send(name=sent)

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"file": [code]}


@pytest.mark.django_db
def test_files_that_share_a_name_are_each_kept_and_download_as_they_were(
    api, server, storage, send
):
    first = send(name="db.sql.gz", content=b"monday").json()
    second = send(name="backups/db.sql.gz", content=b"tuesday").json()
    third = send(name="C:\\dumps\\db.sql.gz", content=b"wednesday").json()

    assert [backup["name"] for backup in (first, second, third)] == ["db.sql.gz"] * 3
    assert stored(storage, server) == [
        "db.sql.gz-2.sealed",
        "db.sql.gz-3.sealed",
        "db.sql.gz.sealed",
    ]
    for backup, content in (
        (first, b"monday"),
        (second, b"tuesday"),
        (third, b"wednesday"),
    ):
        download = api.get(f"/api/backups/{backup['id']}/download/")
        assert b"".join(download.streaming_content) == content


@pytest.mark.django_db
def test_an_empty_file_is_refused(server, storage, send):
    response = send(content=b"")

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"file": ["empty"]}
    assert stored(storage, server) == []
    assert waiting(storage) == []
    assert logged("backup.upload") == []


@pytest.mark.django_db
def test_the_form_needs_a_server_and_a_file(api, server):
    no_file = post(api, form(server=server.pk))
    no_server = post(api, form(name="db.sql.gz"))
    not_a_uuid = post(api, form(server="web-1", name="db.sql.gz"))
    not_a_file = post(
        api,
        form(server=server.pk)[: -len(f"--{BOUNDARY}--\r\n")]
        + f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="file"\r\n\r\n'
        f"db.sql.gz\r\n--{BOUNDARY}--\r\n".encode(),
    )

    assert {no_file.status_code, no_server.status_code, not_a_uuid.status_code} == {400}
    assert no_file.json()["error"]["fields"] == {"file": ["required"]}
    assert no_server.json()["error"]["fields"] == {"server": ["required"]}
    assert not_a_uuid.json()["error"]["fields"] == {"server": ["invalid"]}
    assert not_a_file.json()["error"]["fields"] == {"file": ["invalid"]}


@pytest.mark.django_db
def test_an_upload_is_a_form_not_json(api, server):
    response = api.post(
        URL, json.dumps({"server": str(server.pk)}), content_type="application/json"
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"


@pytest.mark.django_db
def test_a_file_as_large_as_the_limit_is_kept(settings, send):
    settings.BACKUP_UPLOAD_MAX_BYTES = len(CONTENT)

    assert send().status_code == 201


@pytest.mark.django_db
@pytest.mark.parametrize(
    "size", [len(CONTENT) + 1, 200_000], ids=["one-chunk", "many-chunks"]
)
def test_a_file_larger_than_the_limit_is_refused_as_it_arrives(
    settings, server, storage, send, size
):
    settings.BACKUP_UPLOAD_MAX_BYTES = size - 1

    response = send(content=b"x" * size)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "upload_too_large"
    assert stored(storage, server) == []
    assert waiting(storage) == []
    assert logged("backup.upload") == []
    assert list(BackupFileRepository().active()) == []


@pytest.mark.django_db
def test_a_request_that_says_it_is_too_large_is_refused_before_it_is_read(
    settings, storage, send
):
    settings.BACKUP_UPLOAD_MAX_BYTES = 1024

    response = send(CONTENT_LENGTH=str(1024 + FORM_ALLOWANCE + 1))

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "upload_too_large"
    assert not (storage / ".uploads").exists()


@pytest.mark.parametrize(
    "declared", [None, 1024 + FORM_ALLOWANCE + 1], ids=["sent", "declared"]
)
def test_a_refused_request_reads_as_an_empty_form_afterwards(
    settings, rf, storage, declared
):
    settings.BACKUP_UPLOAD_MAX_BYTES = 1024
    extra = {} if declared is None else {"CONTENT_LENGTH": str(declared)}
    request = rf.generic(
        "POST",
        URL,
        form(server=uuid4(), name="db.sql.gz", content=b"x" * 2048),
        content_type=f"multipart/form-data; boundary={BOUNDARY}",
        **extra,
    )
    request.upload_handlers = [UploadHandler(request)]

    with pytest.raises(UploadTooLarge):
        request.POST

    assert (dict(request.POST), dict(request.FILES)) == ({}, {})
    with pytest.raises(RawPostDataException):
        request.body
    assert waiting(storage) == []


@pytest.mark.django_db
def test_the_service_refuses_a_file_over_the_limit_however_it_came(
    settings, admin, server, storage
):
    settings.BACKUP_UPLOAD_MAX_BYTES = 10
    upload = SimpleUploadedFile("db.sql.gz", b"x" * 11)

    with pytest.raises(UploadTooLarge):
        BackupService(admin).upload(server.pk, upload)

    assert upload.closed
    assert stored(storage, server) == []


@pytest.mark.django_db
def test_an_upload_whose_row_cannot_be_written_takes_its_sealed_file_with_it(
    monkeypatch, admin, server, storage
):
    def broken(self, action, **fields):
        raise RuntimeError("the log is down")

    monkeypatch.setattr(ActivityService, "record", broken)
    upload = SimpleUploadedFile("db.sql.gz", CONTENT)

    with pytest.raises(RuntimeError):
        BackupService(admin).upload(server.pk, upload)

    assert upload.closed
    assert stored(storage, server) == []
    assert list(BackupFileRepository().active()) == []


@pytest.mark.django_db
def test_an_upload_to_a_server_that_is_not_there_is_not_found(
    api, admin, server, storage, send
):
    unknown = send(to=uuid4())
    ServerService(admin).delete(server.pk)
    deleted = send()

    for response in (unknown, deleted):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
    assert stored(storage, server) == []
    assert waiting(storage) == []
    assert logged("backup.upload") == []


@pytest.mark.django_db
def test_an_upload_needs_a_session_and_is_not_read_without_one(
    anonymous, storage, send
):
    response = send(client=anonymous)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_authenticated"
    assert not (storage / ".uploads").exists()
