from __future__ import annotations

from uuid import uuid4

import pytest

from dbs import audit
from tests.manager.envfiles.conftest import ENV, LIST, SECRET
from tests.manager.servers.support import PASSWORD


def reveal(api, version_id, password: str = PASSWORD):
    return api.post(f"{LIST}{version_id}/reveal/", {"password": password})


@pytest.mark.django_db
def test_the_right_password_shows_the_content_and_is_recorded(
    admin, api, server, env_file, pull, logged
):
    version = pull(server)["version"]

    response = reveal(api, version["id"])

    assert response.status_code == 200
    assert response.json() == {"content": ENV.decode()}
    assert response["Cache-Control"] == "no-store"
    [entry] = logged("env.reveal")
    assert (
        entry.status,
        entry.server,
        entry.target,
        entry.data,
        entry.actor,
    ) == (
        audit.SUCCEEDED,
        server,
        str(env_file),
        {"version": version["id"]},
        admin,
    )


@pytest.mark.django_db
def test_a_wrong_password_shows_nothing_and_is_recorded_as_failed(
    api, server, pull, logged
):
    version = pull(server)["version"]

    response = reveal(api, version["id"], "not-my-password")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_password"
    assert SECRET not in response.content.decode()
    [entry] = logged("env.reveal")
    assert (entry.status, entry.error_code, entry.data) == (
        audit.FAILED,
        "invalid_password",
        {"version": version["id"]},
    )


@pytest.mark.django_db
def test_a_missing_password_is_a_form_error_and_not_recorded(api, server, pull, logged):
    version = pull(server)["version"]

    response = api.post(f"{LIST}{version['id']}/reveal/", {})

    assert response.json()["error"]["fields"] == {"password": ["required"]}
    assert logged("env.reveal") == []


@pytest.mark.django_db
def test_an_unknown_version_is_not_found_whichever_password(api):
    for password in (PASSWORD, "wrong"):
        response = reveal(api, uuid4(), password)
        assert (response.status_code, response.json()["error"]["code"]) == (
            404,
            "not_found",
        )


@pytest.mark.django_db
def test_bytes_that_are_not_utf8_show_as_replacement_characters(
    api, server, env_file, pull
):
    env_file.write_bytes(b"A=\xff\xfe\n")
    version = pull(server)["version"]

    assert reveal(api, version["id"]).json() == {"content": "A=��\n"}
