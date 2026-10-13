from __future__ import annotations

import pytest

from dbs.manager.servers.repositories import ServerRepository
from tests.manager.servers.support import PASSWORD

ENV = b"SECRET_KEY=sk_live_very_secret\n"


def download(api, server, path: str, **query):
    return api.get(f"/api/files/{server.pk}/download/", {"path": path, **query})


def link(api, server, path: str, password=None):
    body = {"path": path}
    if password is not None:
        body["account_password"] = password
    return api.post(f"/api/files/{server.pk}/download/", body, format="json")


def body(response) -> bytes:
    return b"".join(response.streaming_content)


def asked(response) -> bool:
    return response.status_code == 400 and response.json()["error"]["fields"] == {
        "account_password": ["required"]
    }


@pytest.fixture
def envs(tree):
    (tree.media / ".env").write_bytes(ENV)
    (tree.media / ".env.production").write_bytes(ENV)
    (tree.media / "settings.ini").write_bytes(ENV)
    (tree.media / "env-link").symlink_to(tree.media / ".env")
    return tree


@pytest.mark.django_db
@pytest.mark.parametrize("name", [".env", ".env.production", "settings.ini"])
def test_a_dotenv_file_needs_the_password(api, server, envs, sessions, logged, name):
    ServerRepository().update(server, env_path=f"{envs.media}/settings.ini")

    response = download(api, server, f"{envs.media}/{name}")
    linked = link(api, server, f"{envs.media}/{name}")

    assert asked(response) and asked(linked)
    assert logged("files.download") == []


@pytest.mark.django_db
def test_a_link_to_a_dotenv_file_needs_the_password_too(
    api, server, envs, sessions, logged
):
    response = download(api, server, f"{envs.media}/env-link")

    assert asked(response)
    [entry] = logged("files.download")
    assert (entry.status, entry.error_code) == ("failed", "required")


@pytest.mark.django_db
def test_any_other_file_downloads_as_before(api, server, envs, sessions):
    linked = link(api, server, f"{envs.media}/logo.png").json()["url"]

    assert "ticket" not in linked
    assert body(api.get(linked)) == b"\x89PNG not really"


@pytest.mark.django_db
def test_the_password_buys_one_download_of_a_dotenv_file(
    api, server, envs, sessions, logged
):
    url = link(api, server, f"{envs.media}/.env", password=PASSWORD).json()["url"]

    first = api.get(url)
    again = api.get(url)

    assert first.status_code == 200 and body(first) == ENV
    assert asked(again)
    assert [entry.status for entry in logged("files.download")] == [
        "failed",
        "succeeded",
    ]


@pytest.mark.django_db
def test_a_wrong_password_is_refused_and_logged(api, admin, server, envs, logged):
    response = link(api, server, f"{envs.media}/.env", password="wrong")

    assert response.json()["error"]["code"] == "invalid_password"
    [entry] = logged("files.download")
    assert (entry.status, entry.error_code, entry.actor) == (
        "failed",
        "invalid_password",
        admin,
    )


@pytest.mark.django_db
def test_a_ticket_is_for_the_file_it_was_given_for(api, server, envs, sessions):
    url = link(api, server, f"{envs.media}/.env", password=PASSWORD).json()["url"]
    ticket = url.split("ticket=")[1]

    other = download(api, server, f"{envs.media}/.env.production", ticket=ticket)

    assert asked(other)
