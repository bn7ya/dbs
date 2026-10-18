from uuid import uuid4

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from dbs import audit
from dbs.manager.activity.services import ActivityService
from dbs.manager.applications.services import ApplicationService
from dbs.manager.middleware import request_origin
from tests.manager.factories import make_application, make_server
from tests.manager.support import PASSWORD

LIST = "/api/activity/"


@pytest.mark.django_db
def test_an_entry_about_a_server_names_it(api, admin, server):
    [entry] = api.get(LIST).json()["results"]

    assert entry["action"] == "server.create"
    assert entry["target"] == "web-1"
    assert entry["actor"] == "sara"
    assert entry["server"] == str(server.pk)
    assert entry["server_name"] == "web-1"
    assert entry["application"] is None and entry["application_name"] is None


@pytest.mark.django_db
def test_an_entry_about_an_application_names_it_and_its_server(
    api, server, application
):
    entry = api.get(LIST, {"action": "application.create"}).json()["results"][0]

    assert entry["target"] == "shop"
    assert entry["application"] == str(application.pk)
    assert entry["application_name"] == "shop"
    assert entry["server"] == str(server.pk)
    assert entry["server_name"] == "web-1"


@pytest.mark.django_db
def test_the_log_filters_by_server_with_its_applications(
    api, admin, server, application
):
    elsewhere = make_application(admin, name="blog", host="10.0.0.9")
    service = ActivityService(admin)
    service.record("server.check", subject=server, status=audit.FAILED)
    service.record("application.check", subject=application)
    service.record("application.check", subject=elsewhere)
    service.record("auth.sign_in")

    def actions(**query):
        results = api.get(LIST, query).json()["results"]
        return [(entry["action"], entry["status"]) for entry in results]

    assert actions(server=server.pk) == [
        ("application.check", "succeeded"),
        ("server.check", "failed"),
        ("application.create", "succeeded"),
        ("server.create", "succeeded"),
    ]
    assert actions(server=server.pk, action="auth.sign_in") == []
    assert actions(server=elsewhere.server.pk, action="application.check") == [
        ("application.check", "succeeded")
    ]
    assert actions(server=uuid4()) == []


@pytest.mark.django_db
def test_the_log_filters_by_one_application(api, admin, server, application):
    neighbour = make_application(admin, name="blog", server=server)
    service = ActivityService(admin)
    service.record("application.check", subject=application, status=audit.FAILED)
    service.record("application.check", subject=neighbour)
    service.record("server.check", subject=server)

    def found(**query):
        results = api.get(LIST, query).json()["results"]
        return [(entry["action"], entry["application_name"]) for entry in results]

    assert found(application=application.pk) == [
        ("application.check", "shop"),
        ("application.create", "shop"),
    ]
    assert found(application=neighbour.pk) == [
        ("application.check", "blog"),
        ("application.create", "blog"),
    ]
    assert found(application=application.pk, action="server.check") == []
    assert found(application=uuid4()) == []


@pytest.mark.django_db
def test_an_old_entry_about_a_server_names_the_application_it_became(
    api, server, application
):
    old = audit.record("server.check", subject=str(application.pk), target="shop")

    def ids(**query):
        return [row["id"] for row in api.get(LIST, query).json()["results"]]

    entry = api.get(f"{LIST}{old.pk}/").json()
    assert entry["application"] == str(application.pk)
    assert entry["application_name"] == "shop"
    assert entry["server"] == str(server.pk)
    assert entry["server_name"] == "web-1"
    assert old.pk in ids(application=application.pk)
    assert old.pk in ids(server=server.pk)


@pytest.mark.django_db
def test_actors_servers_and_applications_cost_no_query_per_entry(
    api, admin, server, application
):
    def queries():
        with CaptureQueriesContext(connection) as captured:
            api.get(LIST)
        return len(captured)

    service = ActivityService(admin)
    service.record("server.check", subject=server)
    service.record("application.check", subject=application)
    few = queries()
    for _ in range(5):
        service.record("server.check", subject=server)
        service.record("application.check", subject=application)

    assert queries() == few


@pytest.mark.django_db
def test_a_deleted_server_keeps_its_name_but_loses_its_link(api, server):
    api.delete(
        f"/api/servers/{server.pk}/", {"account_password": PASSWORD}, format="json"
    )

    results = api.get(LIST, {"server": server.pk}).json()["results"]

    assert [entry["action"] for entry in results] == ["server.delete", "server.create"]
    assert {entry["server_name"] for entry in results} == {"web-1"}
    assert {entry["server"] for entry in results} == {None}


@pytest.mark.django_db
def test_a_removed_application_keeps_its_name_but_loses_its_link(
    api, server, application
):
    api.delete(
        f"/api/applications/{application.pk}/",
        {"account_password": PASSWORD},
        format="json",
    )

    results = api.get(LIST, {"application": application.pk}).json()["results"]

    assert [entry["action"] for entry in results] == [
        "application.delete",
        "application.create",
    ]
    assert {entry["application_name"] for entry in results} == {"shop"}
    assert {entry["application"] for entry in results} == {None}
    assert {entry["server"] for entry in results} == {str(server.pk)}


@pytest.mark.django_db
def test_a_queued_job_about_an_application_reads_as_the_list_shows_it(
    api, admin, server, application
):
    with request_origin({"REMOTE_ADDR": "203.0.113.9"}):
        job = ActivityService(admin).queue(
            "backup.take", subject=application, target="shop"
        )

    body = api.get(f"{LIST}{job.pk}/").json()

    assert body == api.get(LIST, {"action": "backup.take"}).json()["results"][0]
    assert body["status"] == "queued" and body["ip"] == "203.0.113.9"
    assert body["application"] == str(application.pk)
    assert body["application_name"] == "shop"
    assert body["server"] == str(server.pk) and body["server_name"] == "web-1"


@pytest.mark.django_db
@pytest.mark.parametrize("scope", ["server", "application"])
def test_an_applications_unfinished_jobs_of_one_kind_can_be_found(
    api, admin, server, application, scope
):
    service = ActivityService(admin)
    queued = service.queue("backup.run", subject=application, detail={"plan": "id"})
    running = service.queue("backup.take", subject=application)
    ActivityService(None).start(running.pk)
    service.queue("backup.run")
    chosen = {"server": server.pk, "application": application.pk}[scope]

    def found(**query):
        response = api.get(LIST, {scope: chosen, **query})
        return [row["id"] for row in response.json()["results"]]

    assert found(action="backup.run", status="queued") == [queued.pk]
    assert found(action="backup.take", status="running") == [running.pk]
    assert found(status="running") == [running.pk]
    assert found(action="backup.run", status="running") == []


@pytest.mark.django_db
def test_a_server_with_no_applications_lists_only_its_own_entries(api, admin):
    lone = make_server(admin, name="spare", host="10.0.0.8")
    ApplicationService(admin).create(server=make_server(admin).pk, name="shop")

    results = api.get(LIST, {"server": lone.pk}).json()["results"]

    assert [(entry["action"], entry["target"]) for entry in results] == [
        ("server.create", "spare")
    ]
