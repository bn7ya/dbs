from __future__ import annotations

import os

import pytest

from dbs import audit
from dbs.manager.servers.gateways import ssh_gateway
from tests.manager.servers.support import LocalFile


def download(api, server, path: str):
    return api.get(f"/api/files/{server.pk}/download/", {"path": path})


def body(response) -> bytes:
    return b"".join(response.streaming_content)


@pytest.mark.django_db
def test_a_file_is_streamed_as_an_attachment_and_the_connection_closed_after(
    monkeypatch, api, server, tree, sessions
):
    monkeypatch.setattr(ssh_gateway, "TRANSFER_WINDOW", 4)
    content = b"\x89PNG not really"

    response = download(api, server, f"{tree.media}/logo.png")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/octet-stream"
    assert response["Content-Disposition"] == 'attachment; filename="logo.png"'
    assert response["Content-Length"] == str(len(content))
    assert response["Cache-Control"] == "no-store"
    chunks = list(response.streaming_content)
    assert b"".join(chunks) == content
    assert len(chunks) == 4
    response.close()
    assert [session.closed for session in sessions] == [True]
    assert sessions[0].sftp.opened[0].closed


@pytest.mark.django_db
def test_a_download_is_recorded_with_its_path_and_size(
    admin, api, server, tree, sessions, logged
):
    body(download(api, server, f"{tree.media}/Docs/report.pdf"))

    [entry] = logged("files.download")
    assert (entry.status, entry.actor, entry.server) == (
        audit.SUCCEEDED,
        admin,
        server,
    )
    assert (entry.target, entry.data) == (
        f"{tree.media}/Docs/report.pdf",
        {"size": 8},
    )


@pytest.mark.django_db
def test_a_file_that_grew_since_it_was_opened_stops_at_its_size(
    monkeypatch, api, server, tree, sessions
):
    readv = LocalFile.readv

    def growing(self, chunks):
        (tree.media / "Readme.md").write_bytes(b"# media, and more since")
        return readv(self, chunks)

    monkeypatch.setattr(LocalFile, "readv", growing)

    response = download(api, server, f"{tree.media}/Readme.md")

    assert response["Content-Length"] == "7"
    assert body(response) == b"# media"


@pytest.mark.django_db
def test_a_name_beyond_ascii_is_named_for_every_browser(api, server, tree, sessions):
    (tree.media / "نسخة.sql").write_bytes(b"x")

    response = download(api, server, f"{tree.media}/نسخة.sql")

    assert response["Content-Disposition"] == (
        "attachment; filename*=utf-8''%D9%86%D8%B3%D8%AE%D8%A9.sql"
    )


@pytest.mark.django_db
def test_a_name_a_header_cannot_carry_is_cleaned(api, server, tree, sessions):
    (tree.media / "a\nb.txt").write_bytes(b"x")

    response = download(api, server, f"{tree.media}/a\nb.txt")

    assert response.status_code == 200
    assert response["Content-Disposition"] == 'attachment; filename="ab.txt"'


@pytest.mark.django_db
def test_an_empty_file_downloads_empty(api, server, tree, sessions):
    (tree.media / "empty").write_bytes(b"")

    response = download(api, server, f"{tree.media}/empty")

    assert (response["Content-Length"], body(response)) == ("0", b"")


@pytest.mark.django_db
def test_a_link_to_a_file_in_an_allowed_folder_downloads_that_file_named_as_the_link(
    api, server, tree, sessions
):
    response = download(api, server, f"{tree.media}/logo-link")

    assert response["Content-Disposition"] == 'attachment; filename="logo-link"'
    assert body(response) == b"\x89PNG not really"


@pytest.mark.django_db
@pytest.mark.parametrize("relative", ["secret-link", "escape/passwd"])
def test_a_link_out_of_the_allowed_folders_is_refused_and_recorded(
    api, server, tree, sessions, logged, relative
):
    response = download(api, server, f"{tree.media}/{relative}")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "path_outside_roots"
    [entry] = logged("files.download")
    assert (entry.status, entry.error_code, entry.target) == (
        audit.FAILED,
        "path_outside_roots",
        f"{tree.media}/{relative}",
    )
    assert [session.closed for session in sessions] == [True]


@pytest.mark.django_db
def test_a_path_outside_the_allowed_folders_is_refused_unreached_and_recorded(
    api, server, tree, sessions, logged
):
    response = download(api, server, str(tree.outside / "passwd"))

    assert response.status_code == 403
    assert sessions == []
    [entry] = logged("files.download")
    assert entry.error_code == "path_outside_roots"


@pytest.mark.django_db
@pytest.mark.parametrize("relative", ["Docs", "docs-link", ""])
def test_a_folder_is_not_a_file(api, server, tree, sessions, logged, relative):
    response = download(api, server, f"{tree.media}/{relative}")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "not_a_file"
    assert logged("files.download")[0].error_code == "not_a_file"
    assert [session.closed for session in sessions] == [True]


@pytest.mark.django_db
def test_a_pipe_is_not_a_file(api, server, tree, sessions):
    os.mkfifo(tree.media / "pipe")

    response = download(api, server, f"{tree.media}/pipe")

    assert response.json()["error"]["code"] == "not_a_file"


@pytest.mark.django_db
def test_a_file_that_is_not_there_is_remote_not_found(
    api, server, tree, sessions, logged
):
    response = download(api, server, f"{tree.media}/missing.png")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "remote_not_found"
    assert logged("files.download")[0].error_code == "remote_not_found"


@pytest.mark.django_db
def test_a_download_needs_a_path(api, server, sessions, logged):
    response = api.get(f"/api/files/{server.pk}/download/")

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"path": ["required"]}
    assert logged("files.download") == []


@pytest.mark.django_db
def test_a_download_needs_a_session(anonymous, server, tree, sessions):
    response = download(anonymous, server, f"{tree.media}/logo.png")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_authenticated"
    assert sessions == []


@pytest.mark.django_db
def test_a_path_is_recorded_printable_and_by_its_end_when_it_is_too_long(
    api, server, tree, sessions, logged
):
    deep = f"{tree.media}/" + "deeper/" * 200 + "a\nb.txt"

    response = download(api, server, deep)

    assert response.status_code == 404
    [entry] = logged("files.download")
    printable = deep.replace("\n", "")
    assert len(entry.target) == 1024
    assert entry.target == "…" + printable[-1023:]
