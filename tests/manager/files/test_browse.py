from __future__ import annotations

import os
from uuid import uuid4

import pytest

from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.applications.models import Application
from dbs.manager.applications.services import ApplicationService
from dbs.manager.servers.exceptions import HostKeyChanged, SSHUnreachable
from tests.manager.factories import make_application
from tests.manager.servers.support import PASSWORD, refusing_with

ENTRY = {"name", "path", "kind", "size", "modified", "mode"}
MOMENT = 1_790_000_000


def url(application) -> str:
    return f"/api/files/{application.pk}/"


def names(response) -> list[str]:
    return names_of(response.json())


def names_of(page: dict) -> list[str]:
    return [entry["name"] for entry in page["results"]]


def bind(source, destination: str) -> dict:
    return {"type": "bind", "source": str(source), "destination": destination}


def in_a_container(admin, roots: list[str], mounts: list[dict]) -> Application:
    return make_application(
        admin,
        name="shop",
        host="10.0.0.20",
        kind=Application.Kind.CONTAINER,
        engine=Application.Engine.DOCKER,
        container_name="shop-web",
        file_roots=roots,
        mounts=mounts,
    )


@pytest.mark.django_db
def test_the_first_allowed_folder_is_listed_when_no_path_is_given(
    api, application, tree, sessions
):
    response = api.get(url(application))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "path",
        "parent",
        "root",
        "roots",
        "count",
        "next",
        "previous",
        "results",
    }
    assert (body["path"], body["parent"], body["root"]) == (
        str(tree.media),
        None,
        str(tree.media),
    )
    assert body["roots"] == tree.roots
    assert (body["count"], body["next"], body["previous"]) == (9, None, None)
    assert all(set(entry) == ENTRY for entry in body["results"])
    assert [session.closed for session in sessions] == [True]


@pytest.mark.django_db
def test_an_empty_path_is_the_same_as_none(api, application, tree, sessions):
    assert api.get(url(application), {"path": ""}).json()["path"] == str(tree.media)


@pytest.mark.django_db
def test_folders_come_first_then_names_ignoring_case(api, application, tree, sessions):
    (tree.media / "zeta").mkdir()
    (tree.media / "Alpha.txt").write_bytes(b"")

    response = api.get(url(application))

    assert names(response) == [
        "assets",
        "Docs",
        "shared",
        "zeta",
        "Alpha.txt",
        "docs-link",
        "escape",
        "logo-link",
        "logo.png",
        "Readme.md",
        "secret-link",
    ]


@pytest.mark.django_db
def test_each_entry_is_described_as_itself(api, application, tree, sessions):
    os.utime(tree.media / "logo.png", (MOMENT, MOMENT))
    (tree.media / "logo.png").chmod(0o640)

    listed = {
        entry["name"]: entry for entry in api.get(url(application)).json()["results"]
    }

    assert listed["logo.png"] == {
        "name": "logo.png",
        "path": f"{tree.media}/logo.png",
        "kind": "file",
        "size": len(b"\x89PNG not really"),
        "modified": "2026-09-21T14:13:20Z",
        "mode": "rw-r-----",
    }
    assert (listed["Docs"]["kind"], listed["Docs"]["size"]) == ("folder", None)
    assert (listed["escape"]["kind"], listed["escape"]["size"]) == ("link", None)
    assert listed["docs-link"]["kind"] == "link"


@pytest.mark.django_db
def test_a_subfolder_is_listed_with_the_way_up(api, application, tree, sessions):
    response = api.get(url(application), {"path": f"{tree.media}/Docs/"})

    body = response.json()
    assert (body["path"], body["parent"], body["root"]) == (
        f"{tree.media}/Docs",
        str(tree.media),
        str(tree.media),
    )
    assert body["results"][0]["path"] == f"{tree.media}/Docs/report.pdf"


@pytest.mark.django_db
def test_another_allowed_folder_is_listed_as_its_own_root(
    api, application, tree, sessions
):
    body = api.get(url(application), {"path": str(tree.backups)}).json()

    assert (body["root"], body["parent"]) == (str(tree.backups), None)
    assert [entry["name"] for entry in body["results"]] == ["db.sql.gz"]


@pytest.mark.django_db
def test_a_listing_is_paginated_and_the_links_keep_the_folder(
    api, application, tree, sessions
):
    first = api.get(url(application), {"path": str(tree.media), "page_size": 4}).json()
    second = api.get(first["next"]).json()

    assert first["count"] == 9
    assert names_of(first) == ["assets", "Docs", "shared", "docs-link"]
    assert second["path"] == str(tree.media)
    assert names_of(second) == [
        "escape",
        "logo-link",
        "logo.png",
        "Readme.md",
    ]
    assert second["previous"] is not None


@pytest.mark.django_db
def test_a_page_past_the_end_is_not_found(api, application, sessions):
    response = api.get(url(application), {"page": 99})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.django_db
def test_a_link_to_a_folder_inside_an_allowed_folder_opens_where_it_leads(
    api, application, tree, sessions
):
    body = api.get(url(application), {"path": f"{tree.media}/docs-link"}).json()

    assert (body["path"], body["parent"]) == (
        f"{tree.media}/docs-link",
        str(tree.media),
    )
    assert [entry["path"] for entry in body["results"]] == [
        f"{tree.media}/docs-link/report.pdf"
    ]


@pytest.mark.django_db
def test_an_allowed_folder_configured_through_a_link_is_listed(
    api, application, tree, sessions
):
    (tree.media / "shared" / "notes.txt").write_bytes(b"")

    body = api.get(url(application), {"path": str(tree.alias)}).json()

    assert (body["path"], body["root"]) == (str(tree.alias), str(tree.alias))
    assert [entry["path"] for entry in body["results"]] == [f"{tree.alias}/notes.txt"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "relative", ["escape", "escape/", "escape/passwd", "Docs/../escape"]
)
def test_a_link_that_leads_out_of_the_allowed_folders_is_refused(
    api, application, tree, sessions, relative
):
    response = api.get(url(application), {"path": f"{tree.media}/{relative}"})

    if ".." in relative:
        assert response.status_code == 400
        assert response.json()["error"]["fields"] == {
            "path": ["absolute_path_required"]
        }
    else:
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "path_outside_roots"


@pytest.mark.django_db
def test_a_path_outside_the_allowed_folders_is_refused_before_the_server_is_reached(
    api, application, tree, sessions
):
    for path in ("/etc", str(tree.outside), f"{tree.media}2", str(tree.base)):
        response = api.get(url(application), {"path": path})
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "path_outside_roots"

    assert sessions == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("path", "fields"),
    [
        ("srv/app/media", ["absolute_path_required"]),
        ("/srv/app/media/../../etc", ["absolute_path_required"]),
        ("/srv/app/media/a\x00b", ["null_characters_not_allowed"]),
        ("/" + "x" * 4096, ["max_length"]),
    ],
    ids=["relative", "climb", "nul", "too-long"],
)
def test_a_path_that_is_not_one_is_a_field_error(
    api, application, sessions, path, fields
):
    response = api.get(url(application), {"path": path})

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"path": fields}
    assert sessions == []


@pytest.mark.django_db
@pytest.mark.parametrize("relative", ["missing", "logo.png", "Docs/missing/deeper"])
def test_a_folder_that_is_not_there_is_remote_not_found(
    api, application, tree, sessions, relative
):
    response = api.get(url(application), {"path": f"{tree.media}/{relative}"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "remote_not_found"


@pytest.mark.django_db
def test_an_allowed_folder_that_is_not_on_the_server_is_remote_not_found(
    admin, api, application, tree, sessions
):
    ApplicationService(admin).update(
        application.pk,
        account_password=PASSWORD,
        file_roots=[f"{tree.base}/missing/deeper"],
    )

    response = api.get(url(application))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "remote_not_found"


@pytest.mark.django_db
def test_an_application_with_no_allowed_folders_says_so(
    admin, api, application, sessions
):
    ApplicationService(admin).update(
        application.pk, account_password=PASSWORD, file_roots=[]
    )

    response = api.get(url(application))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "no_allowed_folders"
    assert sessions == []


@pytest.mark.django_db
def test_an_application_that_is_not_there_is_not_found(
    admin, api, application, sessions
):
    unknown = api.get(f"/api/files/{uuid4()}/")
    ApplicationService(admin).delete(application.pk, account_password=PASSWORD)
    deleted = api.get(url(application))

    for response in (unknown, deleted):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (SSHUnreachable(), 502, "ssh_unreachable"),
        (HostKeyChanged(), 409, "host_key_changed"),
    ],
)
def test_a_server_that_cannot_be_reached_says_why(
    monkeypatch, api, application, error, status, code
):
    monkeypatch.setattr(
        "dbs.manager.servers.services.connection_service.connect", refusing_with(error)
    )

    response = api.get(url(application))

    assert response.status_code == status
    assert response.json()["error"]["code"] == code


@pytest.mark.django_db
def test_listing_is_not_recorded(api, application, sessions):
    api.get(url(application))
    api.get(url(application), {"path": "/etc"})

    assert [entry.action for entry in ActivityRepository().filtered()] == [
        "application.create",
        "server.create",
    ]


@pytest.mark.django_db
def test_a_listing_needs_a_session(anonymous, application, sessions):
    response = anonymous.get(url(application))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_authenticated"
    assert sessions == []


@pytest.mark.django_db
def test_a_container_applications_roots_are_offered_at_their_host_paths(
    admin, api, tree, sessions
):
    application = in_a_container(
        admin,
        ["/app/media", "/app/backups", "/app/static"],
        [bind(tree.media, "/app/media"), bind(tree.backups, "/app/backups/")],
    )

    body = api.get(url(application)).json()

    assert body["roots"] == [str(tree.media), str(tree.backups)]
    assert (body["path"], body["root"]) == (str(tree.media), str(tree.media))
    assert "logo.png" in names_of(body)
    other = api.get(url(application), {"path": str(tree.backups)}).json()
    assert names_of(other) == ["db.sql.gz"]


@pytest.mark.django_db
def test_a_container_root_inside_a_mount_is_offered_where_that_mount_puts_it(
    admin, api, tree, sessions
):
    application = in_a_container(
        admin,
        ["/app/media/Docs"],
        [bind(tree.media.parent, "/app"), bind(tree.backups, "/app/media/backups")],
    )

    body = api.get(url(application)).json()

    assert body["roots"] == [f"{tree.media}/Docs"]
    assert names_of(body) == ["report.pdf"]


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/app/static", "/app/media"])
def test_a_container_path_or_a_root_on_no_mount_is_not_offered(
    admin, api, tree, sessions, path
):
    application = in_a_container(
        admin, ["/app/media", "/app/static"], [bind(tree.media, "/app/media")]
    )

    response = api.get(url(application), {"path": path})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "path_outside_roots"
    assert sessions == []


@pytest.mark.django_db
def test_a_container_application_whose_roots_are_on_no_mount_has_no_folders(
    admin, api, tree, sessions
):
    application = in_a_container(
        admin, ["/app", "/app/static"], [bind(tree.media, "/app/media")]
    )

    response = api.get(url(application))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "no_allowed_folders"
    assert sessions == []
