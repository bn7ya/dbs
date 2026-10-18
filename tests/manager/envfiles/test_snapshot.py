from __future__ import annotations

from datetime import timedelta

import pytest

from dbs import audit
from dbs.manager.applications.services import ApplicationService
from dbs.manager.envfiles.services.env_snapshot_service import snapshot_env_files
from dbs.manager.scheduler import TASKS
from tests.manager.envfiles.conftest import LIST
from tests.manager.support import PASSWORD


def snapshot() -> None:
    snapshot_env_files()


def outcomes(logged) -> dict[str, tuple]:
    return {
        entry.application.name: (entry.status, entry.error_code, entry.data)
        for entry in logged("env.pull")
    }


@pytest.mark.django_db
def test_every_application_is_pulled_and_one_that_fails_does_not_stop_the_rest(
    admin, make_application, application, env_file, network, versions, logged
):
    down = make_application(name="a-down", host="10.0.0.9", env_path=str(env_file))
    network.unreachable.add(down.server.host)
    make_application(
        name="b-missing", host="10.0.0.7", env_path=str(env_file.with_name("gone.env"))
    )
    make_application(name="c-no-env", host="10.0.0.8")
    deleted = make_application(
        name="d-deleted", host="10.0.0.10", env_path=str(env_file)
    )
    ApplicationService(admin).delete(deleted.pk, account_password=PASSWORD)

    snapshot()

    assert outcomes(logged) == {
        "a-down": (audit.FAILED, "ssh_unreachable", {}),
        "b-missing": (audit.FAILED, "remote_not_found", {}),
        "web-1": (audit.SUCCEEDED, "", {"created": True}),
    }
    assert {(entry.actor, entry.ip) for entry in logged("env.pull")} == {(None, None)}
    [kept] = versions(application)
    assert (kept.source, kept.created_by) == ("scheduled", None)


@pytest.mark.django_db
def test_a_snapshot_keeps_nothing_new_when_the_file_did_not_change(
    api, application, network, versions, logged
):
    snapshot()
    snapshot()

    assert len(versions(application)) == 1
    assert [entry.data for entry in logged("env.pull")] == [
        {"created": False},
        {"created": True},
    ]
    [row] = api.get(LIST, {"application": application.pk}).json()["results"]
    assert (row["source"], row["taken_by"]) == ("scheduled", None)


def test_the_scheduler_takes_the_snapshot_daily():
    assert TASKS["snapshot_env_files"] == (
        timedelta(days=1),
        "dbs.manager.envfiles.services.env_snapshot_service.snapshot_env_files",
    )
