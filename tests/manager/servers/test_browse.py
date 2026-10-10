from __future__ import annotations

import pytest

from tests.manager.remote import scripted_hosts


def browse(server_id, **query):
    return f"/api/servers/{server_id}/browse/", query


@pytest.fixture
def tree(tmp_path, monkeypatch):
    home = tmp_path / "home"
    app = home / "app"
    (app / "shop").mkdir(parents=True)
    (app / "manage.py").write_text("")
    (app / ".env").write_text("SECRET_KEY=x\n")
    (app / "Readme.md").write_text("hello")
    (home / "notes.txt").write_text("")
    monkeypatch.chdir(home)
    return {"home": str(home), "app": str(app)}


@pytest.mark.django_db
def test_browsing_opens_the_home_folder(api, configured_server, tree, monkeypatch):
    scripted_hosts(monkeypatch)

    response = api.get(*browse(configured_server.pk))

    assert response.status_code == 200
    body = response.json()
    assert body["path"] == body["home"] == tree["home"]
    assert body["project"] is False
    assert [(entry["name"], entry["kind"]) for entry in body["results"]] == [
        ("app", "folder"),
        ("notes.txt", "file"),
    ]
    assert body["results"][0]["path"] == f"{tree['home']}/app"


@pytest.mark.django_db
def test_a_folder_lists_folders_first_and_says_it_is_a_project(
    api, configured_server, tree, monkeypatch
):
    scripted_hosts(monkeypatch)

    body = api.get(*browse(configured_server.pk, path=tree["app"])).json()

    assert body["path"] == tree["app"]
    assert body["parent"] == tree["home"]
    assert body["project"] is True
    assert [entry["name"] for entry in body["results"]] == [
        "shop",
        ".env",
        "manage.py",
        "Readme.md",
    ]
    assert body["count"] == 4


@pytest.mark.django_db
def test_the_root_folder_has_no_parent(api, configured_server, tree, monkeypatch):
    scripted_hosts(monkeypatch)

    body = api.get(*browse(configured_server.pk, path="/")).json()

    assert body["path"] == "/" and body["parent"] is None


@pytest.mark.django_db
def test_a_listing_is_paged(api, configured_server, tree, monkeypatch):
    scripted_hosts(monkeypatch)

    body = api.get(*browse(configured_server.pk, path=tree["app"], page_size=2)).json()

    assert body["count"] == 4
    assert len(body["results"]) == 2
    assert body["next"] is not None


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["srv/app", "/srv/../etc"])
def test_a_path_that_is_not_absolute_is_refused(
    api, configured_server, monkeypatch, path
):
    scripted_hosts(monkeypatch)

    response = api.get(*browse(configured_server.pk, path=path))

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"path": ["absolute_path_required"]}


@pytest.mark.django_db
def test_a_folder_that_is_not_there_is_not_found(
    api, configured_server, tree, monkeypatch
):
    scripted_hosts(monkeypatch)

    response = api.get(*browse(configured_server.pk, path=f"{tree['home']}/gone"))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "remote_not_found"
