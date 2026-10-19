from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.utils import timezone

import dbs
from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.applications.models import Application
from dbs.manager.applications.repositories import ApplicationRepository
from dbs.manager.applications.services import ApplicationService
from dbs.manager.servers.services import ServerConnectionService
from tests.manager.factories import make_application, make_server
from tests.manager.remote import scripted_hosts
from tests.manager.servers.support import (
    BACKUP_PASSPHRASE,
    MEDIA_ROOT,
    PASSWORD,
    PROJECT_DIR,
    PYTHON,
    connecting_to,
    healthy_remote,
)
from tests.manager.support import logged, needs_partial_unique_constraints

LIST = "/api/applications/"
CONNECT = "dbs.manager.servers.services.connection_service.connect"
APPLICATION_FIELDS = {
    "id",
    "name",
    "server",
    "kind",
    "engine",
    "compose_project",
    "compose_service",
    "compose_files",
    "container_name",
    "project_dir",
    "workdir",
    "python_path",
    "manage_path",
    "settings_module",
    "remote_backup_dir",
    "mounts",
    "file_roots",
    "env_path",
    "env_location",
    "has_backup_passphrase",
    "last_check_status",
    "last_check_error",
    "last_checked_at",
    "last_check_report",
    "last_health",
    "timeout_in_container",
    "deploy_steps",
    "discovered_at",
    "created_at",
    "updated_at",
}


def detail(application_id, action="") -> str:
    return f"{LIST}{application_id}/{action}"


def new_application(server, **overrides) -> dict:
    return {
        "server": str(server.pk),
        "name": "shop",
        "account_password": PASSWORD,
        "project_dir": PROJECT_DIR,
        "python_path": PYTHON,
        "backup_passphrase": BACKUP_PASSPHRASE,
        **overrides,
    }


@pytest.mark.django_db
def test_adding_an_application_asks_for_the_account_password(api, server):
    payload = new_application(server)
    del payload["account_password"]

    response = api.post(LIST, payload, format="json")

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"account_password": ["required"]}
    assert not Application.objects.exists()


@pytest.mark.django_db
def test_a_wrong_account_password_adds_nothing(api, server):
    response = api.post(
        LIST, new_application(server, account_password="not-it"), format="json"
    )

    assert response.json()["error"]["code"] == "invalid_password"
    assert not Application.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("manage_path", '-cimport os; os.system("id")'),
        ("manage_path", "-m"),
        ("manage_path", "../other/manage.py"),
        ("manage_path", "settings.py"),
        ("python_path", "-c"),
        ("python_path", "/bin/sh"),
        ("python_path", "/usr/bin/env"),
        ("python_path", "/srv/../tmp/python3"),
        ("python_path", "sh"),
    ],
)
def test_a_python_or_manage_py_that_is_not_one_is_refused(api, server, field, value):
    response = api.post(LIST, new_application(server, **{field: value}), format="json")

    assert response.status_code == 400
    assert field in response.json()["error"]["fields"]
    assert not Application.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("python_path", "manage_path"),
    [
        ("python3", "manage.py"),
        ("python", "src/manage.py"),
        ("python3.12", "/app/manage.py"),
        ("/srv/shop/.venv/bin/python", "/srv/shop/manage.py"),
        ("/opt/venv/bin/python3.13", "manage.py"),
        ("/usr/local/bin/pypy3", "manage.py"),
    ],
)
def test_a_python_and_a_manage_py_are_named_as_they_are(
    api, server, python_path, manage_path
):
    response = api.post(
        LIST,
        new_application(server, python_path=python_path, manage_path=manage_path),
        format="json",
    )

    assert response.status_code == 201, response.json()
    assert (response.json()["python_path"], response.json()["manage_path"]) == (
        python_path,
        manage_path,
    )


@pytest.mark.django_db
def test_adding_an_application_puts_it_on_its_server_without_its_passphrase(
    api, server
):
    response = api.post(LIST, new_application(server), format="json")

    assert response.status_code == 201
    body = response.json()
    assert set(body) == APPLICATION_FIELDS
    assert body["server"] == {
        "id": str(server.pk),
        "name": server.name,
        "host": server.host,
        "port": server.port,
        "connection_state": "unknown",
    }
    assert (body["project_dir"], body["python_path"]) == (PROJECT_DIR, PYTHON)
    assert body["has_backup_passphrase"] is True
    assert body["discovered_at"] is None
    assert BACKUP_PASSPHRASE not in response.content.decode()
    assert "sealed" not in response.content.decode()
    [entry] = logged("application.create")
    assert (entry.subject, entry.target_name) == (body["id"], "shop")


@pytest.mark.django_db
def test_an_application_left_to_its_defaults_runs_on_the_host(api, server):
    body = api.post(
        LIST,
        {"server": str(server.pk), "name": "shop", "account_password": PASSWORD},
        format="json",
    ).json()

    assert (body["kind"], body["engine"]) == ("host", "")
    assert body["python_path"] == "python3"
    assert body["manage_path"] == "manage.py"
    assert body["remote_backup_dir"] == "/var/backups/dbs"
    assert (body["file_roots"], body["mounts"], body["compose_files"]) == ([], [], [])
    assert (body["project_dir"], body["workdir"]) == ("", "")
    assert (body["env_path"], body["env_location"]) == ("", "host")


@pytest.mark.django_db
def test_an_application_found_by_discovery_says_when(api, server):
    before = timezone.now()

    body = api.post(
        LIST, new_application(server, discovered=True), format="json"
    ).json()

    stored = ApplicationRepository().get(body["id"])
    assert stored.discovered_at is not None and stored.discovered_at >= before


@pytest.mark.django_db
def test_an_application_without_a_passphrase_gets_a_generated_one(api, server):
    payload = new_application(server)
    del payload["backup_passphrase"]
    body = api.post(LIST, payload, format="json").json()

    shown = api.post(detail(body["id"], "passphrase/"), {"password": PASSWORD})

    assert len(shown.json()["passphrase"]) >= 40


@pytest.mark.django_db
def test_an_application_on_a_server_that_does_not_exist_is_not_found(api):
    response = api.post(
        LIST,
        {"server": "00000000-0000-0000-0000-000000000000", "name": "shop"},
        format="json",
    )

    assert response.status_code == 404
    assert not Application.objects.exists()


@pytest.mark.django_db
def test_an_application_needs_a_server_and_a_name(api):
    response = api.post(LIST, {}, format="json")

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {
        "name": ["required"],
        "server": ["required"],
    }


@pytest.mark.django_db
def test_every_path_must_be_absolute(api, server):
    response = api.post(
        LIST,
        new_application(
            server,
            project_dir="srv/app",
            workdir="app",
            env_path="/srv/app/../.env",
            remote_backup_dir="backups",
            file_roots=["/srv/media", "media"],
        ),
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {
        "project_dir": ["absolute_path_required"],
        "workdir": ["absolute_path_required"],
        "env_path": ["absolute_path_required"],
        "remote_backup_dir": ["absolute_path_required"],
        "file_roots": ["absolute_path_required"],
    }


@pytest.mark.django_db
def test_paths_are_normalised_and_roots_deduplicated(api, server):
    response = api.post(
        LIST,
        new_application(
            server,
            project_dir="/srv//app/",
            remote_backup_dir="/var/backups/./dbs/",
            file_roots=["/srv/media", "/srv/media/", "//srv/static"],
        ),
        format="json",
    )

    body = response.json()
    assert body["project_dir"] == "/srv/app"
    assert body["remote_backup_dir"] == "/var/backups/dbs"
    assert body["file_roots"] == ["/srv/media", "/srv/static"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "mount",
    [
        {"source": "srv/media", "destination": "/app/media"},
        {"source": "/srv/media", "destination": "app/media"},
        {"source": "/srv/../etc", "destination": "/app/media"},
    ],
)
def test_a_mount_maps_one_absolute_path_to_another(api, server, mount):
    response = api.post(
        LIST,
        new_application(
            server,
            kind="container",
            engine="docker",
            container_name="shop-web-1",
            mounts=[mount],
        ),
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"mounts": ["absolute_path_required"]}
    assert not Application.objects.exists()


@pytest.mark.django_db
def test_a_container_application_keeps_its_mounts(api, server):
    mounts = [
        {
            "type": "bind",
            "source": "/srv/shop/media",
            "destination": "/app/media",
            "rw": True,
        },
        {
            "type": "volume",
            "source": "/var/lib/docker/volumes/static/_data",
            "destination": "/app/static",
            "rw": False,
        },
    ]

    body = api.post(
        LIST,
        new_application(
            server,
            kind="container",
            engine="podman",
            container_name="shop-web-1",
            workdir="/app",
            mounts=mounts,
        ),
        format="json",
    ).json()

    assert (body["kind"], body["engine"], body["container_name"]) == (
        "container",
        "podman",
        "shop-web-1",
    )
    assert body["mounts"] == mounts
    assert body["workdir"] == "/app"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "settings_module", ["config/settings", "-c import os", "config..settings"]
)
def test_a_settings_module_must_be_a_dotted_module_path(api, server, settings_module):
    response = api.post(
        LIST, new_application(server, settings_module=settings_module), format="json"
    )

    assert response.json()["error"]["fields"] == {"settings_module": ["invalid"]}


@pytest.mark.django_db
def test_a_name_in_use_is_refused(api, application, server):
    response = api.post(
        LIST, new_application(server, name=application.name), format="json"
    )

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"name": ["name_taken"]}


@pytest.mark.django_db
def test_two_applications_may_share_a_server(api, application, server):
    response = api.post(LIST, new_application(server, name="blog"), format="json")

    assert response.status_code == 201
    assert ApplicationRepository().on_server(server.pk).count() == 2


@pytest.mark.django_db
def test_a_removed_applications_name_is_free_again(api, application, server):
    api.delete(detail(application.pk), {"account_password": PASSWORD}, format="json")

    response = api.post(
        LIST, new_application(server, name=application.name), format="json"
    )

    assert response.status_code == 201


@pytest.mark.django_db
@needs_partial_unique_constraints
def test_a_name_taken_between_the_check_and_the_write_is_still_name_taken(
    api, monkeypatch, application, server
):
    monkeypatch.setattr(
        ApplicationRepository,
        "name_in_use",
        lambda self, name, excluding=None: False,
    )

    response = api.post(
        LIST, new_application(server, name=application.name), format="json"
    )

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"name": ["name_taken"]}


@pytest.mark.django_db
def test_the_list_is_paginated_searchable_by_name_server_and_host(
    api, admin, application, server
):
    other = make_server(admin, name="db-1", host="db-1.example.com")
    make_application(admin, name="blog", server=other)

    everything = api.get(LIST)
    by_name = api.get(LIST, {"search": "BLO"})
    by_server = api.get(LIST, {"search": "web-1"})
    by_host = api.get(LIST, {"search": "example.com"})

    body = everything.json()
    assert set(body) == {"count", "next", "previous", "results"}
    assert [row["name"] for row in body["results"]] == ["blog", "web-1"]
    assert set(body["results"][0]) == {
        "id",
        "name",
        "server",
        "kind",
        "engine",
        "compose_service",
        "container_name",
        "project_dir",
        "last_check_status",
        "last_checked_at",
    }
    assert body["results"][0]["server"]["name"] == "db-1"
    assert [row["name"] for row in by_name.json()["results"]] == ["blog"]
    assert [row["name"] for row in by_server.json()["results"]] == ["web-1"]
    assert [row["name"] for row in by_host.json()["results"]] == ["blog"]
    assert BACKUP_PASSPHRASE not in everything.content.decode()


@pytest.mark.django_db
def test_the_list_filters_by_server_and_leaves_removed_applications_out(
    api, admin, application, server
):
    make_application(admin, name="shop", server=server)
    gone = make_application(admin, name="old", server=server)
    ApplicationService(admin).delete(gone.pk, account_password=PASSWORD)
    other = make_server(admin, name="db-1", host="10.0.0.6")
    make_application(admin, name="blog", server=other)

    on_server = api.get(LIST, {"server": str(server.pk)}).json()["results"]
    on_other = api.get(LIST, {"server": str(other.pk)}).json()["results"]
    searched = api.get(LIST, {"server": str(server.pk), "search": "shop"}).json()

    assert [row["name"] for row in on_server] == ["shop", "web-1"]
    assert [row["name"] for row in on_other] == ["blog"]
    assert [row["name"] for row in searched["results"]] == ["shop"]


@pytest.mark.django_db
def test_a_server_filter_that_is_not_an_id_is_refused(api):
    response = api.get(LIST, {"server": "web-1"})

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"server": ["invalid"]}


@pytest.mark.django_db
def test_the_detail_carries_no_secrets(api, application):
    response = api.get(detail(application.pk))

    assert response.status_code == 200
    assert set(response.json()) == APPLICATION_FIELDS
    assert BACKUP_PASSPHRASE not in response.content.decode()


@pytest.mark.django_db
def test_an_unknown_application_is_not_found(api):
    response = api.get(detail("00000000-0000-0000-0000-000000000000"))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def application_as_sent(application) -> dict:
    return {
        "name": application.name,
        "kind": application.kind,
        "engine": application.engine,
        "project_dir": application.project_dir,
        "python_path": application.python_path,
        "manage_path": application.manage_path,
        "settings_module": application.settings_module,
        "remote_backup_dir": application.remote_backup_dir,
        "file_roots": application.file_roots,
        "env_path": application.env_path,
        "env_location": application.env_location,
        "mounts": application.mounts,
        "compose_files": application.compose_files,
    }


@pytest.mark.django_db
def test_a_rename_needs_no_password_even_sent_with_every_setting(api, application):
    response = api.patch(
        detail(application.pk),
        application_as_sent(application) | {"name": "web-2"},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["name"] == "web-2"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "change",
    [
        {"project_dir": "/srv/other"},
        {"python_path": "/usr/bin/python3"},
        {"manage_path": "src/manage.py"},
        {"settings_module": "config.settings.dev"},
        {"remote_backup_dir": "/var/backups/other"},
        {"file_roots": ["/etc"]},
        {"env_path": "/srv/other/.env"},
        {"env_location": "container"},
        {"backup_passphrase": "another"},
        {"kind": "container", "engine": "docker", "container_name": "web"},
        {"workdir": "/app"},
        {"mounts": [{"source": "/srv", "destination": "/app"}]},
    ],
)
def test_changing_anything_but_the_name_needs_the_users_password(
    api, application, change
):
    before = api.get(detail(application.pk)).json()

    response = api.patch(detail(application.pk), change, format="json")

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"account_password": ["required"]}
    assert api.get(detail(application.pk)).json() == before
    assert list(ActivityRepository().filtered(action="application.update")) == []


@pytest.mark.django_db
def test_a_wrong_password_changes_nothing_and_is_logged(api, application):
    before = api.get(detail(application.pk)).json()

    response = api.patch(
        detail(application.pk),
        {"env_path": "/srv/other/.env", "account_password": f"{PASSWORD}-typo"},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_password"
    assert api.get(detail(application.pk)).json() == before
    [entry] = ActivityRepository().filtered(action="application.update")
    assert (entry.status, entry.error_code) == ("failed", "invalid_password")
    assert entry.data == {"fields": ["env_path"]}


@pytest.mark.django_db
def test_the_users_password_lets_the_change_through(api, application):
    response = api.patch(
        detail(application.pk),
        {"env_path": "/srv/other/.env", "account_password": PASSWORD},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["env_path"] == "/srv/other/.env"
    [entry] = ActivityRepository().filtered(action="application.update")
    assert (entry.status, entry.data) == ("succeeded", {"fields": ["env_path"]})


@pytest.mark.django_db
def test_a_wrong_field_is_reported_before_the_password_is_asked_for(api, application):
    response = api.patch(
        detail(application.pk),
        {"env_path": "relative", "account_password": "wrong"},
        format="json",
    )

    assert response.json()["error"]["fields"] == {
        "env_path": ["absolute_path_required"]
    }
    assert list(ActivityRepository().filtered(action="application.update")) == []


@pytest.mark.django_db
def test_an_update_may_replace_the_backup_passphrase(api, admin, application):
    api.patch(
        detail(application.pk),
        {"backup_passphrase": "a-new-passphrase", "account_password": PASSWORD},
        format="json",
    )

    stored = ApplicationRepository().get(application.pk)
    assert (
        ServerConnectionService(admin).backup_passphrase(stored) == "a-new-passphrase"
    )


@pytest.mark.django_db
def test_an_optional_path_can_be_cleared(api, application):
    response = api.patch(
        detail(application.pk),
        {"env_path": "", "project_dir": "", "account_password": PASSWORD},
        format="json",
    )

    assert (response.json()["env_path"], response.json()["project_dir"]) == ("", "")


@pytest.mark.django_db
def test_moving_back_to_the_host_drops_the_engine(api, admin, server):
    shop = make_application(
        admin,
        name="shop",
        server=server,
        kind="container",
        engine="docker",
        container_name="shop-web-1",
    )

    response = api.patch(
        detail(shop.pk), {"kind": "host", "account_password": PASSWORD}, format="json"
    )

    assert (response.json()["kind"], response.json()["engine"]) == ("host", "")


@pytest.fixture
def fresh(admin, server):
    return make_application(
        admin, name="shop", server=server, project_dir=PROJECT_DIR, python_path=PYTHON
    )


@pytest.mark.django_db
def test_settings_found_while_adding_need_no_password_for_an_hour(api, fresh):
    found = {
        "remote_backup_dir": "/srv/found/backups",
        "file_roots": [MEDIA_ROOT],
        "env_path": "/srv/found/.env",
        "discovered": True,
    }

    allowed = api.patch(detail(fresh.pk), found, format="json")
    secret = api.patch(detail(fresh.pk), {"backup_passphrase": "x"}, format="json")

    assert allowed.status_code == 200
    assert allowed.json()["remote_backup_dir"] == "/srv/found/backups"
    assert allowed.json()["discovered_at"] is not None
    assert secret.status_code == 400
    assert secret.json()["error"]["fields"] == {"account_password": ["required"]}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "changes",
    [
        {"python_path": "/srv/found/.venv/bin/python"},
        {"manage_path": "src/manage.py"},
        {"project_dir": "/srv/found"},
        {"workdir": "/app"},
        {"settings_module": "found.settings"},
        {"kind": "compose", "engine": "docker", "compose_service": "backend"},
        {"kind": "container", "engine": "podman", "container_name": "other"},
    ],
)
def test_what_runs_on_the_server_needs_the_password_even_while_adding(
    api, fresh, changes
):
    asked = api.patch(detail(fresh.pk), changes, format="json")
    given = api.patch(
        detail(fresh.pk), {**changes, "account_password": PASSWORD}, format="json"
    )

    assert asked.status_code == 400
    assert asked.json()["error"]["fields"] == {"account_password": ["required"]}
    assert given.status_code == 200, given.json()


@pytest.mark.django_db
def test_a_wrong_password_is_refused_even_where_none_is_needed(api, fresh):
    response = api.patch(
        detail(fresh.pk),
        {"project_dir": "/srv/found", "account_password": "not-the-password"},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_password"
    assert ApplicationRepository().get(fresh.pk).project_dir == PROJECT_DIR


@pytest.mark.django_db
def test_after_an_hour_a_passed_check_or_for_someone_else_settings_need_the_password(
    api, admin, server
):
    older = make_application(admin, name="old", server=server)
    ApplicationRepository().update(
        older, created_at=timezone.now() - timedelta(hours=2)
    )
    other = UserRepository().create(username="omar", password=PASSWORD)
    theirs = make_application(other, name="theirs", server=server)
    checked = make_application(admin, name="checked", server=server)
    ApplicationRepository().update(
        checked,
        last_checked_at=timezone.now(),
        last_check_status=Application.CheckStatus.OK,
    )

    for found in (older, theirs, checked):
        response = api.patch(
            detail(found.pk), {"project_dir": "/srv/found"}, format="json"
        )
        assert response.status_code == 400
        assert response.json()["error"]["fields"] == {"account_password": ["required"]}


@pytest.mark.django_db
def test_a_check_that_did_not_pass_leaves_the_settings_open_to_fix(api, fresh):
    ApplicationRepository().update(
        fresh,
        last_checked_at=timezone.now(),
        last_check_status=Application.CheckStatus.PROBLEM,
    )

    response = api.patch(
        detail(fresh.pk), {"remote_backup_dir": "/srv/app/backups"}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["remote_backup_dir"] == "/srv/app/backups"


@pytest.mark.django_db
def test_removing_an_application_needs_the_password_and_keeps_the_row(
    api, admin, application
):
    asked = api.delete(detail(application.pk))
    wrong = api.delete(
        detail(application.pk), {"account_password": "wrong"}, format="json"
    )
    kept = ApplicationRepository().active().filter(pk=application.pk).exists()
    removed = api.delete(
        detail(application.pk), {"account_password": PASSWORD}, format="json"
    )

    assert asked.json()["error"]["fields"] == {"account_password": ["required"]}
    assert wrong.json()["error"]["code"] == "invalid_password"
    assert kept
    assert removed.status_code == 204
    assert api.get(detail(application.pk)).status_code == 404
    gone = ApplicationRepository().all_including_deleted().get(pk=application.pk)
    assert gone.deleted_at is not None
    assert [
        (entry.status, entry.error_code, entry.actor)
        for entry in logged("application.delete")
    ] == [("succeeded", "", admin), ("failed", "invalid_password", admin)]


@pytest.mark.django_db
def test_removing_an_application_leaves_its_server(api, application, server):
    api.delete(detail(application.pk), {"account_password": PASSWORD}, format="json")

    assert api.get(f"/api/servers/{server.pk}/").status_code == 200


@pytest.mark.django_db
def test_a_check_returns_the_application_with_the_versions_compared(
    api, monkeypatch, application
):
    monkeypatch.setattr(CONNECT, connecting_to(healthy_remote()))

    response = api.post(detail(application.pk, "check/"))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == APPLICATION_FIELDS | {
        "local_version",
        "remote_version",
        "installed",
        "compatible",
    }
    assert body["last_check_status"] == "ok"
    assert (body["local_version"], body["installed"], body["compatible"]) == (
        dbs.__version__,
        True,
        True,
    )


@pytest.mark.django_db
def test_the_passphrase_needs_the_users_password(api, application):
    response = api.post(detail(application.pk, "passphrase/"), {"password": "wrong"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_password"
    assert BACKUP_PASSPHRASE not in response.content.decode()
    [entry] = logged("application.passphrase_reveal")
    assert (entry.status, entry.error_code) == ("failed", "invalid_password")


@pytest.mark.django_db
def test_the_passphrase_is_shown_and_never_cached(api, application):
    response = api.post(detail(application.pk, "passphrase/"), {"password": PASSWORD})

    assert response.status_code == 200
    assert response.json() == {"passphrase": BACKUP_PASSPHRASE}
    assert response["Cache-Control"] == "no-store"
    [entry] = logged("application.passphrase_reveal")
    assert (entry.status, entry.subject) == ("succeeded", str(application.pk))


@pytest.mark.django_db
def test_the_passphrase_is_captured_from_the_application_and_sealed(
    api, admin, monkeypatch, server
):
    shop = make_application(
        admin,
        name="shop",
        server=server,
        project_dir=PROJECT_DIR,
        python_path=PYTHON,
        settings_module="shop.settings",
        backup_passphrase=BACKUP_PASSPHRASE,
    )
    hosts = scripted_hosts(monkeypatch)
    hosts.answer(
        "10.0.0.5",
        [PYTHON, "manage.py", "dbs_key", "--show"],
        (0, "derived-remote-passphrase\n", "Store this somewhere safe."),
    )

    response = api.post(detail(shop.pk, "passphrase/capture/"))

    assert response.status_code == 200
    assert response.json() == {"captured": True}
    stored = ApplicationRepository().get(shop.pk)
    assert ServerConnectionService(admin).backup_passphrase(stored) == (
        "derived-remote-passphrase"
    )
    [run] = hosts.runs("10.0.0.5")
    assert run["stdin"] is None
    assert run["setup"] == [
        f"cd {PROJECT_DIR} || exit 1",
        "export DJANGO_SETTINGS_MODULE=shop.settings",
    ]
    [entry] = logged("application.passphrase_capture")
    assert entry.subject == str(shop.pk)
    assert "derived-remote-passphrase" not in json.dumps(
        [entry.data, entry.target_name]
    )


@pytest.mark.django_db
def test_a_capture_that_fails_keeps_the_stored_passphrase(
    api, admin, monkeypatch, application
):
    hosts = scripted_hosts(monkeypatch)
    hosts.answer(
        "10.0.0.5", [PYTHON, "manage.py", "dbs_key", "--show"], (1, "", "boom")
    )

    response = api.post(detail(application.pk, "passphrase/capture/"))

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "remote_command_failed"
    stored = ApplicationRepository().get(application.pk)
    assert ServerConnectionService(admin).backup_passphrase(stored) == BACKUP_PASSPHRASE
    assert logged("application.passphrase_capture")[0].status == "failed"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", ""),
        ("post", ""),
        ("post", "discover/"),
        ("get", "{id}/"),
        ("patch", "{id}/"),
        ("delete", "{id}/"),
        ("post", "{id}/check/"),
        ("post", "{id}/passphrase/"),
        ("post", "{id}/passphrase/capture/"),
    ],
)
def test_every_endpoint_needs_a_session(anonymous, application, method, path):
    url = LIST + path.format(id=application.pk)

    response = getattr(anonymous, method)(url, {})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_authenticated"
