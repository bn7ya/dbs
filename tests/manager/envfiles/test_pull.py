from __future__ import annotations

from uuid import uuid4

import pytest

from dbs import audit
from dbs.manager.applications.services import ApplicationService
from dbs.manager.servers.gateways import RemoteHost
from dbs.manager.servers.gateways.ssh_gateway import READ_SMALL
from dbs.manager.vault import fingerprint, unseal
from tests.manager.envfiles.conftest import CONTAINER, ENV, LIST
from tests.manager.servers.support import PASSWORD, LocalSftp

KEYS = ["SECRET_KEY", "DEBUG", "DATABASE_URL"]


def refusing(error: Exception):
    def refuse(self, *args, **kwargs):
        raise error

    return refuse


@pytest.mark.django_db
def test_a_pull_keeps_the_file_sealed_with_its_key_names(
    admin, api, application, env_file, network, versions, logged
):
    response = api.post(f"{LIST}pull/", {"application": application.pk})

    assert response.status_code == 200
    body = response.json()
    [version] = versions(application)
    assert body == {
        "created": True,
        "version": {
            "id": str(version.pk),
            "application": str(application.pk),
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
        entry.application,
        entry.target,
        entry.data,
        entry.actor,
    ) == (
        audit.SUCCEEDED,
        application,
        str(env_file),
        {"created": True},
        admin,
    )
    assert [session.closed for session in network.opened] == [True]
    assert (network.runs, network.feeds) == ([], [])


@pytest.mark.django_db
def test_an_unchanged_file_is_not_kept_again(api, application, pull, versions, logged):
    first = pull(application)

    again = pull(application)

    assert again == {"created": False, "version": first["version"]}
    assert len(versions(application)) == 1
    assert [entry.data for entry in logged("env.pull")] == [
        {"created": False},
        {"created": True},
    ]


@pytest.mark.django_db
def test_a_changed_file_is_kept_as_a_new_version(application, env_file, pull, versions):
    pull(application)
    env_file.write_bytes(ENV + b"NEW_KEY=1\n")

    again = pull(application)

    assert again["created"] is True
    assert again["version"]["keys"] == [*KEYS, "NEW_KEY"]
    assert [version.source for version in versions(application)] == ["pulled", "pulled"]
    assert str(versions(application)[0].pk) == again["version"]["id"]


@pytest.mark.django_db
def test_the_same_file_at_another_path_is_kept_again(
    admin, application, env_file, pull, versions
):
    pull(application)
    moved = env_file.with_name("production.env")
    moved.write_bytes(ENV)
    ApplicationService(admin).update(
        application.pk, account_password=PASSWORD, env_path=str(moved)
    )

    again = pull(application)

    assert (again["created"], again["version"]["path"]) == (True, str(moved))
    assert len(versions(application)) == 2


@pytest.mark.django_db
def test_a_link_is_read_through_to_its_file(application, env_file, pull):
    shared = env_file.with_name("shared.env")
    env_file.rename(shared)
    env_file.symlink_to(shared)

    assert pull(application)["version"]["keys"] == KEYS


@pytest.mark.django_db
def test_an_application_with_no_env_path_is_refused_without_connecting(
    api, make_application, network, logged
):
    application = make_application()

    response = api.post(f"{LIST}pull/", {"application": application.pk})

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
    api, application, env_file, network, logged
):
    env_file.unlink()

    response = api.post(f"{LIST}pull/", {"application": application.pk})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "remote_not_found"
    assert logged("env.pull")[0].error_code == "remote_not_found"


@pytest.mark.django_db
def test_a_folder_at_the_path_is_remote_not_found(api, application, env_file, network):
    env_file.unlink()
    env_file.mkdir()

    response = api.post(f"{LIST}pull/", {"application": application.pk})

    assert (response.status_code, response.json()["error"]["code"]) == (
        404,
        "remote_not_found",
    )


@pytest.mark.django_db
def test_a_file_too_large_is_refused_and_not_kept(
    api, settings, application, env_file, network, versions, logged
):
    settings.ENV_MAX_BYTES = len(ENV) - 1

    response = api.post(f"{LIST}pull/", {"application": application.pk})

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "env_too_large"
    assert versions(application) == []
    assert network.opened[0].sftp.opened == []
    [entry] = logged("env.pull")
    assert (entry.status, entry.error_code) == (audit.FAILED, "env_too_large")


@pytest.mark.django_db
def test_a_file_of_exactly_the_limit_is_kept(settings, application, pull):
    settings.ENV_MAX_BYTES = len(ENV)

    assert pull(application)["created"] is True


@pytest.mark.django_db
def test_a_file_the_server_will_not_let_be_read_is_remote_permission_denied(
    api, monkeypatch, application, network
):
    monkeypatch.setattr(
        LocalSftp, "open", refusing(PermissionError(13, "Permission denied"))
    )

    response = api.post(f"{LIST}pull/", {"application": application.pk})

    assert (response.status_code, response.json()["error"]["code"]) == (
        403,
        "remote_permission_denied",
    )


@pytest.mark.django_db
def test_a_server_that_does_not_answer_is_ssh_unreachable(
    api, application, network, logged
):
    network.unreachable.add(application.server.host)

    response = api.post(f"{LIST}pull/", {"application": application.pk})

    assert (response.status_code, response.json()["error"]["code"]) == (
        502,
        "ssh_unreachable",
    )
    assert logged("env.pull")[0].error_code == "ssh_unreachable"


@pytest.mark.django_db
def test_an_unknown_or_removed_application_is_not_found_and_not_recorded(
    admin, api, application, network, logged
):
    ApplicationService(admin).delete(application.pk, account_password=PASSWORD)

    for application_id in (uuid4(), application.pk):
        response = api.post(f"{LIST}pull/", {"application": application_id})
        assert (response.status_code, response.json()["error"]["code"]) == (
            404,
            "not_found",
        )

    assert logged("env.pull") == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("body", "code"), [({}, "required"), ({"application": "web-1"}, "invalid")]
)
def test_a_pull_needs_an_application_id(api, network, body, code):
    response = api.post(f"{LIST}pull/", body)

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"application": [code]}


@pytest.mark.django_db
def test_versions_are_listed_newest_first_a_page_at_a_time(
    api, make_application, application, env_file, pull
):
    other = make_application(name="web-2", host="10.0.0.6", env_path=str(env_file))
    pull(other)
    ids = []
    for extra in (b"", b"A=1\n", b"B=2\n"):
        env_file.write_bytes(ENV + extra)
        ids.append(pull(application)["version"]["id"])

    first = api.get(LIST, {"application": application.pk, "page_size": 2}).json()
    second = api.get(
        LIST, {"application": application.pk, "page_size": 2, "page": 2}
    ).json()

    assert first["count"] == 3
    assert first["previous"] is None
    assert "page=2" in first["next"]
    assert [row["id"] for row in first["results"]] == ids[:0:-1]
    assert [row["id"] for row in second["results"]] == ids[:1]
    assert second["next"] is None
    assert first["results"][0]["keys"] == [*KEYS, "B"]


@pytest.mark.django_db
def test_an_application_with_no_versions_lists_none(api, application):
    assert api.get(LIST, {"application": application.pk}).json() == {
        "count": 0,
        "next": None,
        "previous": None,
        "results": [],
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("query", "code"), [({}, "required"), ({"application": "nope"}, "invalid")]
)
def test_the_list_needs_an_application_id(api, query, code):
    response = api.get(LIST, query)

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"application": [code]}


@pytest.mark.django_db
def test_one_version_reads_as_it_lists(api, application, pull):
    pulled = pull(application)["version"]

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


@pytest.mark.django_db
def test_a_env_inside_a_container_is_read_there(
    api, settings, in_a_container, container_env, network, versions, logged
):
    application = in_a_container(str(container_env))

    response = api.post(f"{LIST}pull/", {"application": application.pk})

    assert response.status_code == 200
    body = response.json()
    assert (body["created"], body["version"]["path"], body["version"]["keys"]) == (
        True,
        str(container_env),
        KEYS,
    )
    [version] = versions(application)
    assert unseal(version.content_sealed, context="envfiles.content") == ENV
    assert network.runs == [
        [
            "docker",
            "exec",
            CONTAINER,
            application.python_path,
            "-c",
            READ_SMALL,
            str(container_env),
            str(settings.ENV_MAX_BYTES),
        ]
    ]
    assert [session.sftp.opened for session in network.opened] == [[]]
    [entry] = logged("env.pull")
    assert (entry.status, entry.application, entry.target) == (
        audit.SUCCEEDED,
        application,
        str(container_env),
    )


@pytest.mark.django_db
def test_a_env_inside_a_container_that_is_not_there_is_remote_not_found(
    api, in_a_container, container_env, network, versions, logged
):
    container_env.unlink()
    application = in_a_container(str(container_env))

    response = api.post(f"{LIST}pull/", {"application": application.pk})

    assert (response.status_code, response.json()["error"]["code"]) == (
        404,
        "remote_not_found",
    )
    assert versions(application) == []
    assert logged("env.pull")[0].error_code == "remote_not_found"


@pytest.mark.django_db
def test_a_env_inside_a_container_too_large_is_refused_and_not_kept(
    api, settings, in_a_container, container_env, network, versions
):
    settings.ENV_MAX_BYTES = len(ENV) - 1
    application = in_a_container(str(container_env))

    response = api.post(f"{LIST}pull/", {"application": application.pk})

    assert (response.status_code, response.json()["error"]["code"]) == (
        413,
        "env_too_large",
    )
    assert versions(application) == []


@pytest.mark.django_db
def test_a_container_env_on_a_bind_mount_is_read_on_the_host(
    monkeypatch, in_a_container, env_file, pull, network, versions
):
    read = []
    read_small = RemoteHost.read_small

    def spied(self, path, max_bytes):
        read.append(path)
        return read_small(self, path, max_bytes)

    monkeypatch.setattr(RemoteHost, "read_small", spied)
    application = in_a_container(
        "/app/.env",
        mounts=[
            {
                "type": "bind",
                "source": str(env_file.parent),
                "destination": "/app",
                "rw": True,
            }
        ],
    )

    pulled = pull(application)

    assert (pulled["version"]["path"], pulled["version"]["keys"]) == (
        "/app/.env",
        KEYS,
    )
    [version] = versions(application)
    assert unseal(version.content_sealed, context="envfiles.content") == ENV
    assert (network.runs, network.feeds) == ([], [])
    assert read == [str(env_file)]


@pytest.mark.django_db
def test_a_container_application_with_its_env_on_the_host_reads_it_there(
    make_application, env_file, pull, network
):
    application = make_application(
        name="shop",
        kind="container",
        engine="docker",
        container_name=CONTAINER,
        env_path=str(env_file),
        env_location="host",
    )

    assert pull(application)["version"]["keys"] == KEYS
    assert (network.runs, network.feeds) == ([], [])


@pytest.mark.django_db
def test_a_env_in_a_folder_others_can_write_is_never_read(
    api, application, env_file, network, versions
):
    env_file.parent.chmod(0o777)

    response = api.post(f"{LIST}pull/", {"application": application.pk})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "env_folder_shared"
    assert versions(application) == []


@pytest.mark.django_db
def test_a_env_that_links_into_a_folder_others_can_write_is_never_read(
    api, make_application, env_file, network, versions, tmp_path
):
    shared = tmp_path.resolve() / "shared"
    shared.mkdir(mode=0o777)
    shared.chmod(0o777)
    (shared / "id_ed25519").write_bytes(b"PRIVATE KEY")
    linked = env_file.parent / ".env.linked"
    linked.symlink_to(shared / "id_ed25519")
    application = make_application(env_path=str(linked))

    response = api.post(f"{LIST}pull/", {"application": application.pk})

    assert response.json()["error"]["code"] == "env_folder_shared"
    assert versions(application) == []


@pytest.mark.django_db
def test_a_env_linked_into_a_trusted_folder_is_read_where_it_points(
    api, make_application, env_file, network, versions, tmp_path
):
    shared = tmp_path.resolve() / "shared"
    shared.mkdir(mode=0o755)
    (shared / ".env").write_bytes(ENV)
    linked = env_file.parent / ".env.linked"
    linked.symlink_to(shared / ".env")
    application = make_application(env_path=str(linked))

    response = api.post(f"{LIST}pull/", {"application": application.pk})

    assert response.status_code == 200, response.json()
    [version] = versions(application)
    assert unseal(version.content_sealed, context="envfiles.content") == ENV
