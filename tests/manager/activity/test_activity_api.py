from uuid import uuid4

import pytest

from dbs import audit
from dbs.manager.activity.services import ActivityService
from dbs.manager.middleware import request_origin

LIST = "/api/activity/"

SHAPE = {
    "id",
    "action",
    "status",
    "target",
    "detail",
    "error_code",
    "ip",
    "actor",
    "server",
    "server_name",
    "created_at",
    "started_at",
    "finished_at",
}


@pytest.mark.django_db
def test_the_log_needs_a_session(anonymous):
    response = anonymous.get(LIST)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_authenticated"


@pytest.mark.django_db
def test_an_entry_has_the_documented_shape(api, admin):
    with request_origin({"REMOTE_ADDR": "203.0.113.9"}):
        ActivityService(admin).record("auth.sign_in", target="sara", detail={"a": 1})

    body = api.get(LIST).json()

    assert body["count"] == 1 and body["next"] is None and body["previous"] is None
    [entry] = body["results"]
    assert set(entry) == SHAPE
    assert entry["action"] == "auth.sign_in"
    assert entry["status"] == "succeeded"
    assert entry["target"] == "sara"
    assert entry["detail"] == {"a": 1}
    assert entry["error_code"] == ""
    assert entry["actor"] == "sara"
    assert entry["ip"] == "203.0.113.9"
    assert entry["server"] is None and entry["server_name"] is None
    assert entry["started_at"] == entry["finished_at"]


@pytest.mark.django_db
def test_an_entry_without_an_actor_has_nulls(api):
    ActivityService(None).record(
        "auth.sign_in_failed", target="nobody", status="failed"
    )

    [entry] = api.get(LIST).json()["results"]

    assert entry["actor"] is None
    assert entry["ip"] is None


@pytest.mark.django_db
def test_entries_the_core_writes_are_in_the_same_log(api):
    audit.record("backup.create", target="nightly.dbs", data={"size": 10})

    [entry] = api.get(LIST).json()["results"]

    assert (entry["action"], entry["target"], entry["detail"]) == (
        "backup.create",
        "nightly.dbs",
        {"size": 10},
    )


@pytest.mark.django_db
def test_the_newest_entry_comes_first(api, admin):
    service = ActivityService(admin)
    for action in ("auth.sign_in", "server.fingerprint", "auth.sign_out"):
        service.record(action)

    actions = [entry["action"] for entry in api.get(LIST).json()["results"]]

    assert actions == ["auth.sign_out", "server.fingerprint", "auth.sign_in"]


@pytest.mark.django_db
def test_the_log_is_paginated(api, admin):
    service = ActivityService(admin)
    for _ in range(3):
        service.record("auth.sign_in")

    body = api.get(LIST, {"page_size": 2}).json()

    assert body["count"] == 3
    assert len(body["results"]) == 2
    assert "page=2" in body["next"]
    assert len(api.get(LIST, {"page_size": 2, "page": 2}).json()["results"]) == 1


@pytest.mark.django_db
def test_the_log_filters_by_action_status_and_server(api, admin):
    service = ActivityService(admin)
    service.record("server.check", status=audit.FAILED)
    service.record("server.check")
    service.record("auth.sign_in")

    def actions(**query):
        return [
            (row["action"], row["status"])
            for row in api.get(LIST, query).json()["results"]
        ]

    assert actions(action="server.check", status="failed") == [
        ("server.check", "failed")
    ]
    assert actions(server=uuid4()) == []
    assert len(actions(server="", action="", status="")) == 3


@pytest.mark.django_db
def test_an_unknown_status_is_a_field_error(api):
    response = api.get(LIST, {"status": "done"})

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid"
    assert error["fields"] == {"status": ["invalid_status"]}


@pytest.mark.django_db
def test_a_server_that_is_not_a_uuid_is_a_field_error(api):
    response = api.get(LIST, {"server": "web-1"})

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"server": ["invalid"]}


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_the_log_cannot_be_written_through_the_api(api, admin, method):
    entry = ActivityService(admin).record("auth.sign_in")

    assert getattr(api, method)(LIST, {}).status_code == 405
    assert getattr(api, method)(f"{LIST}{entry.pk}/", {}).status_code == 405


@pytest.mark.django_db
def test_one_entry_reads_as_the_list_shows_it(api, admin):
    job = ActivityService(admin).queue("backup.take", target="web-1")

    response = api.get(f"{LIST}{job.pk}/")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == SHAPE
    assert body == api.get(LIST, {"action": "backup.take"}).json()["results"][0]
    assert body["status"] == "queued" and body["started_at"] is None


@pytest.mark.django_db
def test_an_unknown_entry_is_not_found(api):
    response = api.get(f"{LIST}999999/")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
