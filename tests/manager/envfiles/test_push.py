from __future__ import annotations

import os
import stat
from uuid import uuid4

import pytest

from dbs import audit
from dbs.manager.servers.gateways import RemoteHost
from dbs.manager.servers.services import ServerService
from dbs.manager.vault import unseal
from tests.manager.envfiles.conftest import ENV, LIST
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
    admin, api, server, env_file, pull, versions, logged
):
    chosen = pull(server)["version"]
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
    kept = versions(server)
    assert [version.source for version in kept] == ["pushed", "pulled", "pulled"]
    assert str(kept[0].pk) == pushed["id"]
    assert unseal(kept[1].content_sealed, context="envfiles.content") == CHANGED
    assert kept[1].created_by == admin
    [entry] = logged("env.push")
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
        {"from_version": chosen["id"]},
        admin,
    )


@pytest.mark.django_db
def test_a_file_already_kept_is_not_kept_again_before_a_push(
    api, server, pull, versions
):
    chosen = pull(server)["version"]

    push(api, chosen["id"])

    assert [version.source for version in versions(server)] == ["pushed", "pulled"]


@pytest.mark.django_db
def test_a_push_replaces_the_file_in_one_rename_keeping_its_mode(
    api, server, env_file, pull, network
):
    chosen = pull(server)["version"]
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
    api, monkeypatch, server, env_file, pull
):
    chosen = pull(server)["version"]
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
    api, server, env_file, pull, versions
):
    chosen = pull(server)["version"]
    env_file.unlink()

    response = push(api, chosen["id"])

    assert response.status_code == 200
    assert env_file.read_bytes() == ENV
    assert mode_of(env_file) == 0o600
    assert [version.source for version in versions(server)] == ["pushed", "pulled"]


@pytest.mark.django_db
def test_a_link_stays_a_link_and_its_file_is_replaced(api, server, env_file, pull):
    chosen = pull(server)["version"]
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
def test_a_push_writes_the_stored_bytes_exactly(api, server, env_file, pull):
    exact = b"\xef\xbb\xbfA=\xff\r\nB='x'\n"
    env_file.write_bytes(exact)
    chosen = pull(server)["version"]
    env_file.write_bytes(CHANGED)

    push(api, chosen["id"])

    assert env_file.read_bytes() == exact


@pytest.mark.django_db
def test_a_wrong_password_changes_nothing_and_reaches_no_server(
    api, server, env_file, pull, network, versions, logged
):
    chosen = pull(server)["version"]
    env_file.write_bytes(CHANGED)
    before = (env_file.read_bytes(), mode_of(env_file), env_file.stat().st_ino)
    opened = len(network.opened)

    response = push(api, chosen["id"], "not-my-password")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_password"
    assert (env_file.read_bytes(), mode_of(env_file), env_file.stat().st_ino) == before
    assert len(network.opened) == opened
    assert len(versions(server)) == 1
    [entry] = logged("env.push")
    assert (entry.status, entry.error_code, entry.data) == (
        audit.FAILED,
        "invalid_password",
        {"from_version": chosen["id"]},
    )


@pytest.mark.django_db
def test_a_file_too_large_to_keep_is_never_replaced(
    api, settings, server, env_file, pull, versions, logged
):
    chosen = pull(server)["version"]
    env_file.write_bytes(CHANGED * 100)
    settings.ENV_MAX_BYTES = len(CHANGED * 100) - 1

    response = push(api, chosen["id"])

    assert (response.status_code, response.json()["error"]["code"]) == (
        413,
        "env_too_large",
    )
    assert env_file.read_bytes() == CHANGED * 100
    assert len(versions(server)) == 1
    assert logged("env.push")[0].error_code == "env_too_large"


@pytest.mark.django_db
def test_a_folder_at_the_path_is_never_written_over(api, server, env_file, pull):
    chosen = pull(server)["version"]
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
    admin, api, server, env_file, pull
):
    chosen = pull(server)["version"]
    ServerService(admin).update(
        server.pk,
        account_password=PASSWORD,
        env_path=str(env_file.parent / "gone" / ".env"),
    )

    response = push(api, chosen["id"])

    assert (response.status_code, response.json()["error"]["code"]) == (
        404,
        "remote_not_found",
    )


@pytest.mark.django_db
def test_a_server_whose_env_path_was_cleared_is_refused(
    admin, api, server, env_file, pull, network
):
    chosen = pull(server)["version"]
    ServerService(admin).update(server.pk, account_password=PASSWORD, env_path="")
    opened = len(network.opened)

    response = push(api, chosen["id"])

    assert (response.status_code, response.json()["error"]["code"]) == (
        400,
        "env_path_missing",
    )
    assert len(network.opened) == opened
    assert env_file.read_bytes() == ENV


@pytest.mark.django_db
def test_a_version_of_a_deleted_server_is_not_pushed(admin, api, server, pull, logged):
    chosen = pull(server)["version"]
    ServerService(admin).delete(server.pk)

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
