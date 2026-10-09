from __future__ import annotations

import os
from urllib.parse import urlencode

import pytest

from dbs import audit
from tests.manager.servers.support import LocalSftp


def make_folder(api, server, path: str, name: str):
    return api.post(f"/api/files/{server.pk}/folders/", {"path": path, "name": name})


def delete(api, server, path: str):
    return api.delete(f"/api/files/{server.pk}/?{urlencode({'path': path})}")


@pytest.mark.django_db
def test_a_folder_is_made_and_answered_as_an_entry(
    admin, api, server, tree, sessions, logged
):
    response = make_folder(api, server, f"{tree.media}/Docs", "  2026 reports ")

    assert response.status_code == 201
    body = response.json()
    assert {key: body[key] for key in ("name", "path", "kind", "size", "mode")} == {
        "name": "2026 reports",
        "path": f"{tree.media}/Docs/2026 reports",
        "kind": "folder",
        "size": None,
        "mode": "rwxr-xr-x",
    }
    assert (tree.media / "Docs" / "2026 reports").is_dir()
    [entry] = logged("files.create_folder")
    assert (entry.status, entry.actor, entry.server, entry.target) == (
        audit.SUCCEEDED,
        admin,
        server,
        f"{tree.media}/Docs/2026 reports",
    )
    assert [session.closed for session in sessions] == [True]


@pytest.mark.django_db
@pytest.mark.parametrize("taken", ["Docs", "logo.png", "escape"])
def test_a_folder_whose_name_is_taken_is_file_exists(
    api, server, tree, sessions, logged, taken
):
    response = make_folder(api, server, str(tree.media), taken)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "file_exists"
    assert logged("files.create_folder")[0].error_code == "file_exists"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "name", ["a/b", "..", ".", "a\\b", "\x1b[31m", "‮cod.exe", "ن" * 128, "../../etc"]
)
def test_a_name_that_cannot_be_one_is_refused_and_not_recorded(
    api, server, tree, sessions, logged, name
):
    response = make_folder(api, server, str(tree.media), name)

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"name": ["invalid_name"]}
    assert sessions == []
    assert logged("files.create_folder") == []


@pytest.mark.django_db
def test_a_folder_needs_a_name_and_a_place(api, server, sessions):
    response = api.post(f"/api/files/{server.pk}/folders/", {"name": "  "})

    assert response.json()["error"]["fields"] == {
        "path": ["required"],
        "name": ["blank"],
    }


@pytest.mark.django_db
@pytest.mark.parametrize("relative", ["escape", "escape/"])
def test_a_folder_through_a_link_out_of_the_allowed_folders_is_refused(
    api, server, tree, sessions, logged, relative
):
    response = make_folder(api, server, f"{tree.media}/{relative}", "planted")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "path_outside_roots"
    assert sorted(os.listdir(tree.outside)) == ["passwd"]
    assert logged("files.create_folder")[0].error_code == "path_outside_roots"


@pytest.mark.django_db
def test_a_folder_outside_the_allowed_folders_is_refused_unreached(
    api, server, tree, sessions
):
    response = make_folder(api, server, str(tree.base), "planted")

    assert response.status_code == 403
    assert sessions == []
    assert not (tree.base / "planted").exists()


@pytest.mark.django_db
def test_a_folder_in_a_folder_that_is_not_there_is_remote_not_found(
    api, server, tree, sessions
):
    response = make_folder(api, server, f"{tree.media}/missing/deeper", "x")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "remote_not_found"


@pytest.mark.django_db
def test_making_a_folder_needs_a_session(anonymous, server, tree, sessions):
    response = make_folder(anonymous, server, str(tree.media), "x")

    assert response.status_code == 403
    assert sessions == []


@pytest.mark.django_db
def test_a_file_is_deleted_and_recorded_with_its_kind(
    admin, api, server, tree, sessions, logged
):
    response = delete(api, server, f"{tree.media}/logo.png")

    assert response.status_code == 204
    assert not (tree.media / "logo.png").exists()
    [entry] = logged("files.delete")
    assert (
        entry.status,
        entry.actor,
        entry.server,
        entry.target,
        entry.data,
    ) == (
        audit.SUCCEEDED,
        admin,
        server,
        f"{tree.media}/logo.png",
        {"kind": "file"},
    )
    assert [session.closed for session in sessions] == [True]


@pytest.mark.django_db
def test_an_empty_folder_is_deleted(api, server, tree, sessions, logged):
    response = delete(api, server, f"{tree.media}/assets/")

    assert response.status_code == 204
    assert not (tree.media / "assets").exists()
    assert logged("files.delete")[0].detail == {"kind": "folder"}


@pytest.mark.django_db
def test_a_folder_that_holds_anything_is_never_deleted(
    api, server, tree, sessions, logged
):
    response = delete(api, server, f"{tree.media}/Docs")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "folder_not_empty"
    assert (tree.media / "Docs" / "report.pdf").read_bytes() == b"%PDF-1.7"
    assert logged("files.delete")[0].error_code == "folder_not_empty"


@pytest.mark.django_db
@pytest.mark.parametrize("link", ["escape", "secret-link", "docs-link", "logo-link"])
def test_deleting_a_link_removes_the_link_and_never_what_it_points_at(
    api, server, tree, sessions, logged, link
):
    response = delete(api, server, f"{tree.media}/{link}")

    assert response.status_code == 204
    assert not os.path.lexists(tree.media / link)
    assert (tree.outside / "passwd").read_bytes() == b"root:x:0:0"
    assert (tree.media / "Docs" / "report.pdf").exists()
    assert (tree.media / "logo.png").exists()
    assert logged("files.delete")[0].detail == {"kind": "link"}


@pytest.mark.django_db
def test_a_file_reached_through_a_link_out_of_the_allowed_folders_is_never_deleted(
    api, server, tree, sessions, logged
):
    response = delete(api, server, f"{tree.media}/escape/passwd")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "path_outside_roots"
    assert (tree.outside / "passwd").read_bytes() == b"root:x:0:0"
    assert logged("files.delete")[0].error_code == "path_outside_roots"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "spelling", ["{media}", "{media}/", "//{media}/.", "{backups}", "{alias}"]
)
def test_an_allowed_folder_itself_is_never_deleted(
    api, server, tree, sessions, logged, spelling
):
    path = spelling.format(media=tree.media, backups=tree.backups, alias=tree.alias)

    response = delete(api, server, path)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "cannot_delete_root"
    assert sessions == []
    assert tree.media.is_dir() and tree.backups.is_dir() and tree.alias.is_symlink()
    assert logged("files.delete")[0].error_code == "cannot_delete_root"


@pytest.mark.django_db
def test_an_allowed_folder_reached_by_another_path_is_never_deleted(
    api, server, tree, sessions
):
    response = delete(api, server, f"{tree.media}/shared")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "cannot_delete_root"
    assert (tree.media / "shared").is_dir()


@pytest.mark.django_db
def test_deleting_outside_the_allowed_folders_is_refused_unreached(
    api, server, tree, sessions
):
    response = delete(api, server, str(tree.outside / "passwd"))

    assert response.status_code == 403
    assert sessions == []
    assert (tree.outside / "passwd").exists()


@pytest.mark.django_db
def test_deleting_what_is_not_there_is_remote_not_found(
    api, server, tree, sessions, logged
):
    response = delete(api, server, f"{tree.media}/missing.png")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "remote_not_found"
    assert logged("files.delete")[0].error_code == "remote_not_found"


@pytest.mark.django_db
def test_a_file_the_server_will_not_remove_is_remote_permission_denied(
    monkeypatch, api, server, tree, sessions
):
    def refuse(self, path):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(LocalSftp, "remove", refuse)

    response = delete(api, server, f"{tree.media}/logo.png")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "remote_permission_denied"
    assert (tree.media / "logo.png").exists()


@pytest.mark.django_db
def test_a_name_with_spaces_and_arabic_is_deleted(api, server, tree, sessions):
    (tree.media / "نسخة الليل.sql").write_bytes(b"x")

    response = delete(api, server, f"{tree.media}/نسخة الليل.sql")

    assert response.status_code == 204
    assert not (tree.media / "نسخة الليل.sql").exists()


@pytest.mark.django_db
def test_a_delete_needs_a_path(api, server, sessions, logged):
    response = api.delete(f"/api/files/{server.pk}/")

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"path": ["required"]}
    assert logged("files.delete") == []


@pytest.mark.django_db
def test_a_delete_needs_a_session(anonymous, server, tree, sessions):
    response = delete(anonymous, server, f"{tree.media}/logo.png")

    assert response.status_code == 403
    assert (tree.media / "logo.png").exists()
    assert sessions == []
