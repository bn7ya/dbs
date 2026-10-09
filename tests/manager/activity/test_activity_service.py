from __future__ import annotations

import pytest
from django.contrib.auth.models import AnonymousUser
from rest_framework.exceptions import ErrorDetail, ValidationError

from dbs import audit
from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.activity.services import ActivityService
from dbs.manager.middleware import request_origin
from dbs.manager.servers.exceptions import SSHUnreachable


def stored(entry):
    return ActivityRepository().get(entry.pk)


@pytest.mark.django_db
def test_a_recorded_action_is_finished_when_it_is_written(admin, server):
    entry = ActivityService(admin).record(
        "server.delete", server=server, target="web-1", detail={"fields": ["name"]}
    )

    entry = stored(entry)
    assert entry.action == "server.delete"
    assert entry.status == audit.SUCCEEDED
    assert entry.actor == admin
    assert entry.subject == str(server.pk)
    assert entry.target_name == "web-1"
    assert entry.data == {"fields": ["name"]}
    assert entry.error_code == ""
    assert entry.started_at is not None
    assert entry.started_at == entry.finished_at


@pytest.mark.django_db
def test_a_failure_is_recorded_with_its_code(admin):
    entry = ActivityService(admin).record(
        "auth.sign_in_failed",
        target="sara",
        status=audit.FAILED,
        error_code="authentication_failed",
    )

    entry = stored(entry)
    assert entry.status == audit.FAILED
    assert entry.error_code == "authentication_failed"
    assert entry.data == {}
    assert entry.subject == ""


@pytest.mark.django_db
@pytest.mark.parametrize("user", [None, AnonymousUser()])
def test_no_one_signed_in_is_no_actor(user):
    assert stored(ActivityService(user).record("auth.sign_in_failed")).actor is None


@pytest.mark.django_db
def test_the_address_is_the_requests_and_none_outside_one(admin, settings):

    with request_origin({"REMOTE_ADDR": "203.0.113.9"}):
        inside = ActivityService(admin).record("auth.sign_out")
    outside = ActivityService(admin).record("auth.sign_out")

    assert stored(inside).remote_addr == "203.0.113.9"
    assert stored(outside).remote_addr == ""


@pytest.mark.django_db
def test_a_tracked_action_runs_then_succeeds_with_its_detail(admin, server):
    with ActivityService(admin).track(
        "server.check", server=server, target="web-1"
    ) as entry:
        running = stored(entry)
        entry.detail = {"status": "ok"}

    assert running.status == audit.RUNNING
    assert running.started_at is not None
    assert running.finished_at is None
    done = stored(entry)
    assert done.status == audit.SUCCEEDED
    assert done.data == {"status": "ok"}
    assert done.error_code == ""
    assert done.finished_at >= done.started_at


@pytest.mark.django_db
def test_a_tracked_action_that_fails_is_stored_failed_and_the_error_raised(
    admin, server
):
    with (
        pytest.raises(SSHUnreachable),
        ActivityService(admin).track("server.check", server=server) as entry,
    ):
        entry.detail = {"status": "failed"}
        raise SSHUnreachable()

    failed = stored(entry)
    assert failed.status == audit.FAILED
    assert failed.error_code == "ssh_unreachable"
    assert failed.data == {"status": "failed"}
    assert failed.finished_at is not None


@pytest.mark.django_db
def test_a_validation_error_is_stored_with_its_own_code(admin):
    detail = ErrorDetail("Paste the host key as one line.", code="invalid_host_key")

    with (
        pytest.raises(ValidationError),
        ActivityService(admin).track("server.repin") as entry,
    ):
        raise ValidationError({"host_key": [detail]})

    assert stored(entry).error_code == "invalid_host_key"


@pytest.mark.django_db
def test_an_error_without_a_code_is_unexpected(admin):
    with (
        pytest.raises(RuntimeError),
        ActivityService(admin).track("server.check") as entry,
    ):
        raise RuntimeError("boom")

    assert stored(entry).error_code == "unexpected"


@pytest.mark.django_db
def test_a_value_returned_from_the_block_is_still_tracked(admin):
    def fingerprint() -> str:
        with ActivityService(admin).track("server.fingerprint", target="10.0.0.9:22"):
            return "SHA256:abc"

    assert fingerprint() == "SHA256:abc"
    [entry] = ActivityRepository().filtered(action="server.fingerprint")
    assert entry.status == audit.SUCCEEDED


@pytest.mark.django_db
def test_an_unknown_status_is_refused(admin):
    with pytest.raises(ValidationError) as refused:
        ActivityService(admin).list(status="done")

    assert refused.value.get_codes() == {"status": ["invalid_status"]}
