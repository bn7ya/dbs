from __future__ import annotations

import os
import stat
from uuid import uuid4

import pytest

from dbs import audit
from dbs.manager.applications.services import ApplicationService
from dbs.manager.servers.gateways import RemoteHost
from dbs.manager.servers.gateways.ssh_gateway import MODE_OF, READ_SMALL, RECEIVE_FILE
from dbs.manager.vault import unseal
from tests.manager.envfiles.conftest import CONTAINER, ENV, LIST
from tests.manager.servers.support import PASSWORD

CHANGED = b"SECRET_KEY=rotated-on-the-server-0b9e\nDEBUG=1\n"


def push(api, version_id, password: str = PASSWORD):
    return api.post(f"{LIST}{version_id}/push/", {"password": password})


def mode_of(path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def leftovers(folder) -> list[str]:
    return sorted(name for name in os.listdir(folder) if ".part-" in name)


@pytest.mark.django_db
def test_a_push_keeps_what_it_replaces_then_writes_the_version(
    admin, api, application, env_file, pull, network, versions, logged
):
    chosen = pull(application)["version"]
    env_file.write_bytes(CHANGED)

    response = push(api, chosen["id"])

    assert response.status_code == 200
    pushed = response.json()["version"]
    assert (pushed["source"], pushed["path"], pushed["keys"], pushed["taken_by"]) == (
        "pushed",
        str(env_file),
        chosen["keys"],
        "sara",
    )
    assert env_file.read_bytes() == ENV
    kept = versions(application)
    assert [version.source for version in kept] == ["pushed", "pulled", "pulled"]
    assert str(kept[0].pk) == pushed["id"]
    assert unseal(kept[1].content_sealed, context="envfiles.content") == CHANGED
    assert kept[1].created_by == admin
    [entry] = logged("env.push")
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
        {"from_version": chosen["id"]},
        admin,
    )
    assert (network.runs, network.feeds) == ([], [])


@pytest.mark.django_db
def test_a_file_already_kept_is_not_kept_again_before_a_push(
    api, application, pull, versions
):
    chosen = pull(application)["version"]

    push(api, chosen["id"])

    assert [version.source for version in versions(application)] == ["pushed", "pulled"]


@pytest.mark.django_db
def test_a_push_replaces_the_file_in_one_rename_keeping_its_mode(
    api, application, env_file, pull, network
):
    chosen = pull(application)["version"]
    env_file.write_bytes(CHANGED)
    env_file.chmod(0o604)
    before = env_file.stat().st_ino

    push(api, chosen["id"])

    assert env_file.read_bytes() == ENV
    assert mode_of(env_file) == 0o604
    assert env_file.stat().st_ino != before
    assert leftovers(env_file.parent) == []
    assert all(session.closed for session in network.opened)


@pytest.mark.django_db
def test_a_push_gives_the_new_file_the_owner_of_the_one_it_replaces(
    api, monkeypatch, application, env_file, pull
):
    chosen = pull(application)["version"]
    replaced = []
    replace_file = RemoteHost.replace_file

    def spied(self, path, data, *, mode, owner=None):
        replaced.append((path, mode, owner))
        return replace_file(self, path, data, mode=mode, owner=owner)

    monkeypatch.setattr(RemoteHost, "replace_file", spied)

    push(api, chosen["id"])

    found = env_file.stat()
    assert replaced == [(str(env_file), 0o640, (found.st_uid, found.st_gid))]


@pytest.mark.django_db
def test_a_file_that_is_not_there_is_created_for_its_owner_alone(
    api, application, env_file, pull, versions
):
    chosen = pull(application)["version"]
    env_file.unlink()

    response = push(api, chosen["id"])

    assert response.status_code == 200
    assert env_file.read_bytes() == ENV
    assert mode_of(env_file) == 0o600
    assert [version.source for version in versions(application)] == ["pushed", "pulled"]


@pytest.mark.django_db
def test_a_link_stays_a_link_and_its_file_is_replaced(api, application, env_file, pull):
    chosen = pull(application)["version"]
    shared = env_file.with_name("shared.env")
    shared.write_bytes(CHANGED)
    shared.chmod(0o600)
    env_file.unlink()
    env_file.symlink_to(shared)

    push(api, chosen["id"])

    assert env_file.is_symlink()
    assert shared.read_bytes() == ENV
    assert mode_of(shared) == 0o600


@pytest.mark.django_db
def test_a_push_writes_the_stored_bytes_exactly(api, application, env_file, pull):
    exact = b"\xef\xbb\xbfA=\xff\r\nB='x'\n"
    env_file.write_bytes(exact)
    chosen = pull(application)["version"]
    env_file.write_bytes(CHANGED)

    push(api, chosen["id"])

    assert env_file.read_bytes() == exact


@pytest.mark.django_db
def test_a_wrong_password_changes_nothing_and_reaches_no_server(
    api, application, env_file, pull, network, versions, logged
):
    chosen = pull(application)["version"]
    env_file.write_bytes(CHANGED)
    before = (env_file.read_bytes(), mode_of(env_file), env_file.stat().st_ino)
    opened = len(network.opened)

    response = push(api, chosen["id"], "not-my-password")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_password"
    assert (env_file.read_bytes(), mode_of(env_file), env_file.stat().st_ino) == before
    assert len(network.opened) == opened
    assert len(versions(application)) == 1
    [entry] = logged("env.push")
    assert (entry.status, entry.error_code, entry.data) == (
        audit.FAILED,
        "invalid_password",
        {"from_version": chosen["id"]},
    )


@pytest.mark.django_db
def test_a_file_too_large_to_keep_is_never_replaced(
    api, settings, application, env_file, pull, versions, logged
):
    chosen = pull(application)["version"]
    env_file.write_bytes(CHANGED * 100)
    settings.ENV_MAX_BYTES = len(CHANGED * 100) - 1

    response = push(api, chosen["id"])

    assert (response.status_code, response.json()["error"]["code"]) == (
        413,
        "env_too_large",
    )
    assert env_file.read_bytes() == CHANGED * 100
    assert len(versions(application)) == 1
    assert logged("env.push")[0].error_code == "env_too_large"


@pytest.mark.django_db
def test_a_folder_at_the_path_is_never_written_over(api, application, env_file, pull):
    chosen = pull(application)["version"]
    env_file.unlink()
    env_file.mkdir()

    response = push(api, chosen["id"])

    assert (response.status_code, response.json()["error"]["code"]) == (
        404,
        "remote_not_found",
    )
    assert env_file.is_dir()
    assert leftovers(env_file.parent) == []


@pytest.mark.django_db
def test_a_folder_that_is_not_there_is_remote_not_found(
    admin, api, application, env_file, pull
):
    chosen = pull(application)["version"]
    ApplicationService(admin).update(
        application.pk,
        account_password=PASSWORD,
        env_path=str(env_file.parent / "gone" / ".env"),
    )

    response = push(api, chosen["id"])

    assert (response.status_code, response.json()["error"]["code"]) == (
        404,
        "remote_not_found",
    )


@pytest.mark.django_db
def test_an_application_whose_env_path_was_cleared_is_refused(
    admin, api, application, env_file, pull, network
):
    chosen = pull(application)["version"]
    ApplicationService(admin).update(
        application.pk, account_password=PASSWORD, env_path=""
    )
    opened = len(network.opened)

    response = push(api, chosen["id"])

    assert (response.status_code, response.json()["error"]["code"]) == (
        400,
        "env_path_missing",
    )
    assert len(network.opened) == opened
    assert env_file.read_bytes() == ENV


@pytest.mark.django_db
def test_a_version_of_a_removed_application_is_not_pushed(
    admin, api, application, pull, logged
):
    chosen = pull(application)["version"]
    ApplicationService(admin).delete(application.pk, account_password=PASSWORD)

    response = push(api, chosen["id"])

    assert (response.status_code, response.json()["error"]["code"]) == (
        404,
        "not_found",
    )
    assert logged("env.push") == []


@pytest.mark.django_db
def test_an_unknown_version_is_not_found_whichever_password(api, network):
    for password in (PASSWORD, "wrong"):
        response = push(api, uuid4(), password)
        assert (response.status_code, response.json()["error"]["code"]) == (
            404,
            "not_found",
        )


def python_in(application, *arguments: str) -> list[str]:
    return [application.python_path, "-c", *arguments]


@pytest.mark.django_db
def test_a_env_inside_a_container_is_replaced_there_keeping_its_mode(
    api, settings, in_a_container, container_env, pull, network, versions, logged
):
    application = in_a_container(str(container_env))
    chosen = pull(application)["version"]
    container_env.write_bytes(CHANGED)
    before = container_env.stat().st_ino

    response = push(api, chosen["id"])

    assert response.status_code == 200
    assert response.json()["version"]["path"] == str(container_env)
    assert container_env.read_bytes() == ENV
    assert mode_of(container_env) == 0o640
    assert container_env.stat().st_ino != before
    assert leftovers(container_env.parent) == []
    kept = versions(application)
    assert [version.source for version in kept] == ["pushed", "pulled", "pulled"]
    assert unseal(kept[1].content_sealed, context="envfiles.content") == CHANGED
    path = str(container_env)
    limit = str(settings.ENV_MAX_BYTES)
    assert network.runs[1:] == [
        ["docker", "exec", CONTAINER, *python_in(application, READ_SMALL, path, limit)],
        ["docker", "exec", CONTAINER, *python_in(application, MODE_OF, path)],
    ]
    [fed] = network.feeds
    partial = fed[-1]
    assert fed[:-1] == [
        "docker",
        "exec",
        "-i",
        CONTAINER,
        *python_in(application, RECEIVE_FILE, path, str(len(ENV)), "0o640"),
    ]
    assert os.path.dirname(partial) == str(container_env.parent)
    assert ".part-" in os.path.basename(partial)
    assert [session.sftp.opened for session in network.opened] == [[], []]
    [entry] = logged("env.push")
    assert (entry.status, entry.application, entry.target, entry.data) == (
        audit.SUCCEEDED,
        application,
        str(container_env),
        {"from_version": chosen["id"]},
    )


@pytest.mark.django_db
def test_a_env_missing_inside_a_container_is_created_for_its_owner_alone(
    api, in_a_container, container_env, pull, network, versions
):
    application = in_a_container(str(container_env))
    chosen = pull(application)["version"]
    container_env.unlink()

    response = push(api, chosen["id"])

    assert response.status_code == 200
    assert container_env.read_bytes() == ENV
    assert mode_of(container_env) == 0o600
    assert [version.source for version in versions(application)] == [
        "pushed",
        "pulled",
    ]


@pytest.mark.django_db
def test_a_env_inside_a_container_too_large_to_keep_is_never_replaced(
    api, settings, in_a_container, container_env, pull, network, versions
):
    application = in_a_container(str(container_env))
    chosen = pull(application)["version"]
    container_env.write_bytes(CHANGED * 100)
    settings.ENV_MAX_BYTES = len(CHANGED * 100) - 1

    response = push(api, chosen["id"])

    assert (response.status_code, response.json()["error"]["code"]) == (
        413,
        "env_too_large",
    )
    assert container_env.read_bytes() == CHANGED * 100
    assert network.feeds == []
    assert len(versions(application)) == 1


@pytest.mark.django_db
def test_a_container_env_on_a_bind_mount_is_replaced_on_the_host(
    api, in_a_container, env_file, pull, network, versions
):
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
    chosen = pull(application)["version"]
    env_file.write_bytes(CHANGED)

    response = push(api, chosen["id"])

    assert response.status_code == 200
    assert response.json()["version"]["path"] == "/app/.env"
    assert env_file.read_bytes() == ENV
    assert mode_of(env_file) == 0o640
    assert leftovers(env_file.parent) == []
    assert (network.runs, network.feeds) == ([], [])
    assert [version.source for version in versions(application)] == [
        "pushed",
        "pulled",
        "pulled",
    ]
