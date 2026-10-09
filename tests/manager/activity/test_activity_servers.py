from uuid import uuid4

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from dbs import audit
from dbs.manager.activity.services import ActivityService
from dbs.manager.middleware import request_origin

LIST = "/api/activity/"


@pytest.mark.django_db
def test_an_entry_about_a_server_names_it(api, admin, server):
    [entry] = api.get(LIST).json()["results"]

    assert entry["action"] == "server.create"
    assert entry["target"] == "web-1"
    assert entry["actor"] == "sara"
    assert entry["server"] == str(server.pk)
    assert entry["server_name"] == "web-1"


@pytest.mark.django_db
def test_the_log_filters_by_server(api, admin, server):
    service = ActivityService(admin)
    service.record("server.check", server=server, status=audit.FAILED)
    service.record("server.check", server=server)
    service.record("auth.sign_in")

    def actions(**query):
        results = api.get(LIST, query).json()["results"]
        return [(entry["action"], entry["status"]) for entry in results]

    assert actions(server=server.pk) == [
        ("server.check", "succeeded"),
        ("server.check", "failed"),
        ("server.create", "succeeded"),
    ]
    assert actions(server=server.pk, action="auth.sign_in") == []
    assert actions(server=uuid4()) == []


@pytest.mark.django_db
def test_actors_and_servers_cost_no_query_per_entry(api, admin, server):
    def queries():
        with CaptureQueriesContext(connection) as captured:
            api.get(LIST)
        return len(captured)

    service = ActivityService(admin)
    service.record("server.check", server=server)
    few = queries()
    for _ in range(5):
        service.record("server.check", server=server)

    assert queries() == few


@pytest.mark.django_db
def test_a_deleted_server_keeps_its_name_but_loses_its_link(api, server):
    api.delete(f"/api/servers/{server.pk}/")

    results = api.get(LIST, {"server": server.pk}).json()["results"]

    assert [entry["action"] for entry in results] == ["server.delete", "server.create"]
    assert {entry["server_name"] for entry in results} == {"web-1"}
    assert {entry["server"] for entry in results} == {None}


@pytest.mark.django_db
def test_a_queued_job_about_a_server_reads_as_the_list_shows_it(api, admin, server):
    with request_origin({"REMOTE_ADDR": "203.0.113.9"}):
        job = ActivityService(admin).queue("backup.take", server=server, target="web-1")

    body = api.get(f"{LIST}{job.pk}/").json()

    assert body == api.get(LIST, {"action": "backup.take"}).json()["results"][0]
    assert body["status"] == "queued" and body["ip"] == "203.0.113.9"
    assert body["server"] == str(server.pk) and body["server_name"] == "web-1"


@pytest.mark.django_db
def test_a_servers_unfinished_jobs_of_one_kind_can_be_found(api, admin, server):
    service = ActivityService(admin)
    queued = service.queue("backup.run", server=server, detail={"plan": "id"})
    running = service.queue("backup.take", server=server)
    ActivityService(None).start(running.pk)
    service.queue("backup.run")

    def found(**query):
        response = api.get(LIST, {"server": server.pk, **query})
        return [row["id"] for row in response.json()["results"]]

    assert found(action="backup.run", status="queued") == [queued.pk]
    assert found(action="backup.take", status="running") == [running.pk]
    assert found(status="running") == [running.pk]
    assert found(action="backup.run", status="running") == []
