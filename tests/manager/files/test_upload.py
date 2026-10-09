from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from dbs import audit
from dbs.manager.common.uploads import FORM_ALLOWANCE, UploadTooLarge
from dbs.manager.files.services import FileService
from dbs.manager.servers.gateways import RemoteHost
from tests.manager.servers.support import LocalFile, LocalSftp

BOUNDARY = "dbs-manager-files-boundary"
CONTENT = b"%PDF-1.7 the quarterly report"
CSRF_TOKEN = "b" * 32


def form(
    *, path: str | None, name: str | None = "report.pdf", content: bytes = CONTENT
) -> bytes:
    parts = []
    if path is not None:
        parts.append(
            f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="path"\r\n\r\n'
            f"{path}\r\n".encode()
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


def waiting(storage: Path) -> list[Path]:
    uploads = storage / ".uploads"
    return sorted(uploads.iterdir()) if uploads.exists() else []


def partials(folder: Path) -> list[str]:
    return sorted(name for name in os.listdir(folder) if ".part-" in name)


@pytest.fixture
def send(api, server, tree):

    def send(path=None, name="report.pdf", content=CONTENT, *, client=None, **extra):
        return (client or api).generic(
            "POST",
            f"/api/files/{server.pk}/upload/",
            form(
                path=str(tree.media) if path is None else path,
                name=name,
                content=content,
            ),
            content_type=f"multipart/form-data; boundary={BOUNDARY}",
            **extra,
        )

    return send


@pytest.mark.django_db
def test_a_file_is_written_into_the_folder_and_answered_as_an_entry(
    send, tree, storage, sessions
):
    response = send()

    assert response.status_code == 201
    body = response.json()
    assert {key: body[key] for key in ("name", "path", "kind", "size", "mode")} == {
        "name": "report.pdf",
        "path": f"{tree.media}/report.pdf",
        "kind": "file",
        "size": len(CONTENT),
        "mode": "rw-r--r--",
    }
    assert body["modified"] is not None
    target = tree.media / "report.pdf"
    assert target.read_bytes() == CONTENT
    assert stat.S_IMODE(target.stat().st_mode) == 0o644
    assert partials(tree.media) == []
    assert waiting(storage) == []
    assert [session.closed for session in sessions] == [True]


@pytest.mark.django_db
def test_an_upload_is_recorded_with_its_path_and_size(
    admin, server, send, tree, sessions, logged
):
    send(path=f"{tree.media}/assets/")

    [entry] = logged("files.upload")
    assert (entry.status, entry.actor, entry.server) == (
        audit.SUCCEEDED,
        admin,
        server,
    )
    assert entry.target == f"{tree.media}/assets/report.pdf"
    assert entry.data == {"size": len(CONTENT)}
    assert (tree.media / "assets" / "report.pdf").read_bytes() == CONTENT


@pytest.mark.django_db
def test_the_file_waits_privately_on_the_backup_volume_until_the_server_has_it(
    monkeypatch, send, storage, sessions
):
    seen = []
    write_new = RemoteHost.write_new

    def watching(self, source, folder, name):
        path = Path(source.file.name)
        seen.append((path.parent, stat.S_IMODE(path.stat().st_mode), path.read_bytes()))
        return write_new(self, source, folder, name)

    monkeypatch.setattr(RemoteHost, "write_new", watching)

    assert send().status_code == 201

    assert seen == [(storage / ".uploads", 0o600, CONTENT)]
    assert waiting(storage) == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("sent", "kept"),
    [
        ("../../etc/cron.d/x", "x"),
        ("C:\\Users\\sara\\report.pdf", "report.pdf"),
        ("  نسخة الليل.sql  ", "نسخة الليل.sql"),
        ("ن" * 200 + ".sql", "ن" * 125 + ".sql"),
    ],
    ids=["folders", "windows-path", "arabic", "too-long-for-the-server"],
)
def test_a_file_is_named_after_what_follows_its_last_folder(
    send, tree, sessions, sent, kept
):
    response = send(name=sent)

    assert response.status_code == 201
    assert response.json()["name"] == kept
    assert (tree.media / kept).read_bytes() == CONTENT
    assert not (tree.base / "etc" / "cron.d").exists()


@pytest.mark.django_db
def test_an_empty_file_is_a_file(send, tree, sessions):
    response = send(name="__init__.py", content=b"")

    assert response.status_code == 201
    assert response.json()["size"] == 0
    assert (tree.media / "__init__.py").read_bytes() == b""


@pytest.mark.django_db
def test_a_file_as_large_as_the_limit_is_written(settings, send, sessions):
    settings.FILES_UPLOAD_MAX_BYTES = len(CONTENT)

    assert send().status_code == 201


@pytest.mark.django_db
@pytest.mark.parametrize("taken", ["file", "folder", "link"])
def test_a_name_that_is_taken_is_never_written_over(
    send, tree, sessions, logged, taken
):
    target = tree.media / "report.pdf"
    if taken == "file":
        target.write_bytes(b"the original")
    elif taken == "folder":
        target.mkdir()
    else:
        target.symlink_to(tree.outside / "passwd")

    response = send()

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "file_exists"
    assert partials(tree.media) == []
    assert (tree.outside / "passwd").read_bytes() == b"root:x:0:0"
    if taken == "file":
        assert target.read_bytes() == b"the original"
    [entry] = logged("files.upload")
    assert (entry.status, entry.error_code) == (audit.FAILED, "file_exists")


@pytest.mark.django_db
def test_a_name_taken_while_the_file_was_sent_is_never_written_over(
    monkeypatch, send, tree, sessions
):
    rename = LocalSftp.rename

    def beaten(self, old, new):
        Path(new).write_bytes(b"someone else's")
        rename(self, old, new)

    monkeypatch.setattr(LocalSftp, "rename", beaten)

    response = send()

    assert response.status_code == 409
    assert (tree.media / "report.pdf").read_bytes() == b"someone else's"
    assert partials(tree.media) == []


@pytest.mark.django_db
def test_a_server_that_kept_less_than_was_sent_leaves_nothing(
    monkeypatch, send, tree, storage, sessions, logged
):
    write = LocalFile.write
    monkeypatch.setattr(LocalFile, "write", lambda self, data: write(self, data[:-1]))

    response = send()

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "remote_command_failed"
    assert not (tree.media / "report.pdf").exists()
    assert partials(tree.media) == []
    assert waiting(storage) == []
    assert logged("files.upload")[0].error_code == "remote_command_failed"


@pytest.mark.django_db
@pytest.mark.parametrize("relative", ["escape", "escape/"])
def test_a_folder_that_leads_out_of_the_allowed_folders_is_refused(
    send, tree, storage, sessions, logged, relative
):
    response = send(path=f"{tree.media}/{relative}")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "path_outside_roots"
    assert sorted(os.listdir(tree.outside)) == ["passwd"]
    assert waiting(storage) == []
    assert logged("files.upload")[0].error_code == "path_outside_roots"


@pytest.mark.django_db
def test_a_folder_outside_the_allowed_folders_is_refused_unreached(
    send, tree, sessions
):
    response = send(path=str(tree.outside))

    assert response.status_code == 403
    assert sessions == []
    assert sorted(os.listdir(tree.outside)) == ["passwd"]


@pytest.mark.django_db
@pytest.mark.parametrize("relative", ["missing", "logo.png"])
def test_a_folder_that_is_not_there_is_remote_not_found(send, tree, sessions, relative):
    response = send(path=f"{tree.media}/{relative}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "remote_not_found"


@pytest.mark.django_db
def test_a_folder_the_server_will_not_write_to_is_remote_permission_denied(
    monkeypatch, send, tree, sessions
):
    def refuse(self, path, mode="r"):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(LocalSftp, "open", refuse)

    response = send()

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "remote_permission_denied"


@pytest.mark.django_db
@pytest.mark.parametrize("sent", ["   ", " .. ", ". "])
def test_a_name_nothing_is_left_of_is_refused_and_not_recorded(
    send, tree, storage, sessions, logged, sent
):
    response = send(name=sent)

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"file": ["invalid_name"]}
    assert sessions == []
    assert waiting(storage) == []
    assert logged("files.upload") == []


@pytest.mark.django_db
def test_the_form_needs_a_folder_and_a_file(send, sessions):
    no_path = send(path="")
    no_file = send(name=None)

    assert no_path.json()["error"]["fields"] == {"path": ["blank"]}
    assert no_file.json()["error"]["fields"] == {"file": ["required"]}


@pytest.mark.django_db
def test_an_upload_is_a_form_not_json(api, server, tree):
    response = api.post(
        f"/api/files/{server.pk}/upload/",
        json.dumps({"path": str(tree.media)}),
        content_type="application/json",
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "size", [len(CONTENT) + 1, 200_000], ids=["one-chunk", "many-chunks"]
)
def test_a_file_larger_than_the_limit_is_refused_as_it_arrives(
    settings, send, tree, storage, sessions, logged, size
):
    settings.FILES_UPLOAD_MAX_BYTES = size - 1

    response = send(content=b"x" * size)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "upload_too_large"
    assert not (tree.media / "report.pdf").exists()
    assert waiting(storage) == []
    assert sessions == []
    assert logged("files.upload") == []


@pytest.mark.django_db
def test_a_request_that_says_it_is_too_large_is_refused_before_it_is_read(
    settings, send, storage
):
    settings.FILES_UPLOAD_MAX_BYTES = 1024

    response = send(CONTENT_LENGTH=str(1024 + FORM_ALLOWANCE + 1))

    assert response.status_code == 413
    assert not (storage / ".uploads").exists()


@pytest.mark.django_db
def test_the_service_refuses_a_file_over_the_limit_however_it_came(
    settings, admin, server, tree, sessions
):
    settings.FILES_UPLOAD_MAX_BYTES = 10
    upload = SimpleUploadedFile("report.pdf", b"x" * 11)

    with pytest.raises(UploadTooLarge):
        FileService(admin).upload(server.pk, str(tree.media), upload)

    assert upload.closed
    assert sessions == []


@pytest.mark.django_db
def test_only_the_upload_handler_reads_the_body_even_when_the_csrf_check_reads_it_first(
    settings, admin, send, tree, storage, sessions
):
    settings.FILE_UPLOAD_HANDLERS = []
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(admin)
    client.cookies[settings.CSRF_COOKIE_NAME] = CSRF_TOKEN

    refused = send(client=client)
    kept = send(client=client, HTTP_X_CSRFTOKEN=CSRF_TOKEN)

    assert refused.status_code == 403
    assert kept.status_code == 201
    assert (tree.media / "report.pdf").read_bytes() == CONTENT
    assert waiting(storage) == []


@pytest.mark.django_db
def test_an_upload_needs_a_session_and_is_not_read_without_one(
    anonymous, send, storage, sessions
):
    response = send(client=anonymous)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_authenticated"
    assert not (storage / ".uploads").exists()
    assert sessions == []
