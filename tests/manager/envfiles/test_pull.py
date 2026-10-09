from __future__ import annotations

from uuid import uuid4

import pytest

from dbs import audit
from dbs.manager.servers.services import ServerService
from dbs.manager.vault import fingerprint, unseal
from tests.manager.envfiles.conftest import ENV, LIST
from tests.manager.servers.support import PASSWORD, LocalSftp

KEYS = ["SECRET_KEY", "DEBUG", "DATABASE_URL"]


def refusing(error: Exception):
    def refuse(self, *args, **kwargs):
        raise error

    return refuse


@pytest.mark.django_db
def test_a_pull_keeps_the_file_sealed_with_its_key_names(
    admin, api, server, env_file, network, versions, logged
):
    response = api.post(f"{LIST}pull/", {"server": server.pk})

    assert response.status_code == 200
    body = response.json()
    [version] = versions(server)
    assert body == {
        "created": True,
        "version": {
            "id": str(version.pk),
            "server": str(server.pk),
            "path": str(env_file),
            "size": len(ENV),
            "keys": KEYS,
            "source": "pulled",
            "created_at": body["version"]["created_at"],
            "taken_by": "sara",
        },
    }
    assert unseal(version.content_sealed, context="envfiles.content") == ENV
    assert version.fingerprint == fingerprint(ENV, context="envfiles.content")
    assert version.created_by == admin
    [entry] = logged("env.pull")
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
        {"created": True},
        admin,
    )
    assert [session.closed for session in network.opened] == [True]


@pytest.mark.django_db
def test_an_unchanged_file_is_not_kept_again(api, server, pull, versions, logged):
    first = pull(server)

    again = pull(server)

    assert again == {"created": False, "version": first["version"]}
    assert len(versions(server)) == 1
    assert [entry.data for entry in logged("env.pull")] == [
        {"created": False},
        {"created": True},
    ]


@pytest.mark.django_db
def test_a_changed_file_is_kept_as_a_new_version(server, env_file, pull, versions):
    pull(server)
    env_file.write_bytes(ENV + b"NEW_KEY=1\n")

    again = pull(server)

    assert again["created"] is True
    assert again["version"]["keys"] == [*KEYS, "NEW_KEY"]
    assert [version.source for version in versions(server)] == ["pulled", "pulled"]
    assert str(versions(server)[0].pk) == again["version"]["id"]


@pytest.mark.django_db
def test_the_same_file_at_another_path_is_kept_again(
    admin, server, env_file, pull, versions
):
    pull(server)
    moved = env_file.with_name("production.env")
    moved.write_bytes(ENV)
    ServerService(admin).update(
        server.pk, account_password=PASSWORD, env_path=str(moved)
    )

    again = pull(server)

    assert (again["created"], again["version"]["path"]) == (True, str(moved))
    assert len(versions(server)) == 2


@pytest.mark.django_db
def test_a_link_is_read_through_to_its_file(server, env_file, pull):
    shared = env_file.with_name("shared.env")
    env_file.rename(shared)
    env_file.symlink_to(shared)

    assert pull(server)["version"]["keys"] == KEYS


@pytest.mark.django_db
def test_a_server_with_no_env_path_is_refused_without_connecting(
    api, make_server, network, logged
):
    server = make_server()

    response = api.post(f"{LIST}pull/", {"server": server.pk})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "env_path_missing"
    assert network.opened == []
    [entry] = logged("env.pull")
    assert (entry.status, entry.error_code, entry.target) == (
        audit.FAILED,
        "env_path_missing",
        "",
    )


@pytest.mark.django_db
def test_a_file_that_is_not_there_is_remote_not_found(
    api, server, env_file, network, logged
):
    env_file.unlink()

    response = api.post(f"{LIST}pull/", {"server": server.pk})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "remote_not_found"
    assert logged("env.pull")[0].error_code == "remote_not_found"


@pytest.mark.django_db
def test_a_folder_at_the_path_is_remote_not_found(api, server, env_file, network):
    env_file.unlink()
    env_file.mkdir()

    response = api.post(f"{LIST}pull/", {"server": server.pk})

    assert (response.status_code, response.json()["error"]["code"]) == (
        404,
        "remote_not_found",
    )


@pytest.mark.django_db
def test_a_file_too_large_is_refused_and_not_kept(
    api, settings, server, env_file, network, versions, logged
):
    settings.ENV_MAX_BYTES = len(ENV) - 1

    response = api.post(f"{LIST}pull/", {"server": server.pk})

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "env_too_large"
    assert versions(server) == []
    assert network.opened[0].sftp.opened == []
    [entry] = logged("env.pull")
    assert (entry.status, entry.error_code) == (audit.FAILED, "env_too_large")


@pytest.mark.django_db
def test_a_file_of_exactly_the_limit_is_kept(settings, server, pull):
    settings.ENV_MAX_BYTES = len(ENV)

    assert pull(server)["created"] is True


@pytest.mark.django_db
def test_a_file_the_server_will_not_let_be_read_is_remote_permission_denied(
    api, monkeypatch, server, network
):
    monkeypatch.setattr(
        LocalSftp, "open", refusing(PermissionError(13, "Permission denied"))
    )

    response = api.post(f"{LIST}pull/", {"server": server.pk})

    assert (response.status_code, response.json()["error"]["code"]) == (
        403,
        "remote_permission_denied",
    )


@pytest.mark.django_db
def test_a_server_that_does_not_answer_is_ssh_unreachable(api, server, network, logged):
    network.unreachable.add(server.host)

    response = api.post(f"{LIST}pull/", {"server": server.pk})

    assert (response.status_code, response.json()["error"]["code"]) == (
        502,
        "ssh_unreachable",
    )
    assert logged("env.pull")[0].error_code == "ssh_unreachable"


@pytest.mark.django_db
def test_an_unknown_or_deleted_server_is_not_found_and_not_recorded(
    admin, api, server, network, logged
):
    ServerService(admin).delete(server.pk)

    for server_id in (uuid4(), server.pk):
        response = api.post(f"{LIST}pull/", {"server": server_id})
        assert (response.status_code, response.json()["error"]["code"]) == (
            404,
            "not_found",
        )

    assert logged("env.pull") == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("body", "code"), [({}, "required"), ({"server": "web-1"}, "invalid")]
)
def test_a_pull_needs_a_server_id(api, network, body, code):
    response = api.post(f"{LIST}pull/", body)

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"server": [code]}


@pytest.mark.django_db
def test_versions_are_listed_newest_first_a_page_at_a_time(
    api, make_server, server, env_file, pull
):
    other = make_server(name="web-2", host="10.0.0.6", env_path=str(env_file))
    pull(other)
    ids = []
    for extra in (b"", b"A=1\n", b"B=2\n"):
        env_file.write_bytes(ENV + extra)
        ids.append(pull(server)["version"]["id"])

    first = api.get(LIST, {"server": server.pk, "page_size": 2}).json()
    second = api.get(LIST, {"server": server.pk, "page_size": 2, "page": 2}).json()

    assert first["count"] == 3
    assert first["previous"] is None
    assert "page=2" in first["next"]
    assert [row["id"] for row in first["results"]] == ids[:0:-1]
    assert [row["id"] for row in second["results"]] == ids[:1]
    assert second["next"] is None
    assert first["results"][0]["keys"] == [*KEYS, "B"]


@pytest.mark.django_db
def test_a_server_with_no_versions_lists_none(api, server):
    assert api.get(LIST, {"server": server.pk}).json() == {
        "count": 0,
        "next": None,
        "previous": None,
        "results": [],
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("query", "code"), [({}, "required"), ({"server": "nope"}, "invalid")]
)
def test_the_list_needs_a_server_id(api, query, code):
    response = api.get(LIST, query)

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"server": [code]}


@pytest.mark.django_db
def test_one_version_reads_as_it_lists(api, server, pull):
    pulled = pull(server)["version"]

    response = api.get(f"{LIST}{pulled['id']}/")

    assert response.status_code == 200
    assert response.json() == pulled


@pytest.mark.django_db
def test_an_unknown_version_is_not_found(api):
    response = api.get(f"{LIST}{uuid4()}/")

    assert (response.status_code, response.json()["error"]["code"]) == (
        404,
        "not_found",
    )
