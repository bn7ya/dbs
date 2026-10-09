import pytest
from django.test import Client

from dbs.manager import spa

INDEX = b"<!doctype html><html><body><app-root></app-root></body></html>"


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    root = tmp_path / "dbs_manager"
    root.mkdir()
    (root / "index.html").write_bytes(INDEX)
    (root / "main-ABCD1234.js").write_text("console.log('app')")
    (root / "favicon.ico").write_bytes(b"icon")
    (tmp_path / "secret.txt").write_text("not for the browser")
    monkeypatch.setattr(spa, "BUNDLE", root)
    return root


@pytest.fixture
def client():
    return Client()


def test_the_root_returns_the_index_with_a_csrf_cookie(client, bundle, db):
    response = client.get("/")

    assert response.status_code == 200
    assert response.content == INDEX
    assert response["Cache-Control"] == "no-cache"
    assert "csrftoken" in response.cookies


@pytest.mark.parametrize(
    "path", ["/servers/", "/servers/4c1f/backups", "/setup?token=abc"]
)
def test_a_deep_link_returns_the_index(client, bundle, db, path):
    response = client.get(path)

    assert response.status_code == 200
    assert response.content == INDEX


def test_a_hashed_asset_is_cached_for_good(client, bundle):
    response = client.get("/static/dbs_manager/main-ABCD1234.js")

    assert response.status_code == 200
    assert b"".join(response.streaming_content) == b"console.log('app')"
    assert response["Cache-Control"] == "public, max-age=31536000, immutable"


def test_an_unhashed_asset_is_revalidated(client, bundle):
    response = client.get("/static/dbs_manager/favicon.ico")

    assert response.status_code == 200
    assert response["Cache-Control"] == "no-cache"


@pytest.mark.parametrize(
    "path",
    [
        "/static/dbs_manager/../secret.txt",
        "/static/dbs_manager/%2e%2e/secret.txt",
        "/static/dbs_manager/..%2fsecret.txt",
        "/static/dbs_manager//etc/passwd",
    ],
)
def test_a_path_outside_the_bundle_is_refused(client, bundle, path):
    response = client.get(path)

    assert response.status_code in (400, 404)
    assert b"not for the browser" not in b"".join(
        getattr(response, "streaming_content", [response.content])
    )


def test_a_missing_asset_is_not_found(client, bundle):
    assert client.get("/static/dbs_manager/nope.js").status_code == 404


@pytest.mark.parametrize(
    "path", ["/api/nope/", "/api/servers/nope/deeper/", "/api", "/api/"]
)
def test_an_unknown_api_path_is_a_json_404(client, path):
    response = client.get(path)

    assert response.status_code == 404
    assert response["Content-Type"] == "application/json"
    assert response.json()["error"]["code"] == "not_found"


def test_without_a_bundle_the_page_says_how_to_build_one(
    client, tmp_path, monkeypatch, db
):
    monkeypatch.setattr(spa, "BUNDLE", tmp_path / "missing")

    response = client.get("/servers/")

    assert response.status_code == 200
    assert b"scripts/build_manager_ui.sh" in response.content
