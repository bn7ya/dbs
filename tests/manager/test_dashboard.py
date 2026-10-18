from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone

import dbs
from dbs import audit
from dbs.manager.activity.services import ActivityService
from dbs.manager.applications.repositories import ApplicationRepository
from dbs.manager.backups.models import BackupFile, BackupPlan
from dbs.manager.backups.repositories import BackupFileRepository, BackupPlanRepository
from dbs.manager.servers.repositories import ServerRepository
from dbs.models import AuditEvent
from tests.manager.factories import make_application, make_server

DASHBOARD = "/api/dashboard/"
HEALTH = {
    "status": "ok",
    "checks": [],
    "last_backup_at": None,
    "generated_at": "2026-10-09T03:00:00Z",
}
SERVER_KEYS = {
    "id",
    "name",
    "host",
    "check_status",
    "checked_at",
    "connection_state",
    "last_seen_at",
    "applications",
}
APPLICATION_KEYS = {
    "id",
    "name",
    "kind",
    "engine",
    "check_status",
    "checked_at",
    "last_backup",
    "next_plan_run",
    "failures_7d",
    "storage_bytes",
    "health",
}
ACTIVITY_KEYS = {
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
    "application",
    "application_name",
    "connection",
    "created_at",
    "started_at",
    "finished_at",
}


def backup(application, name, kind=BackupFile.Kind.DBS, size=100, **fields):
    return BackupFileRepository().create(
        application=application,
        kind=kind,
        name=name,
        size=size,
        sha256="0" * 64,
        storage_path=f"{application.pk}/{name}",
        validation=BackupFile.Validation.STRUCTURE_OK,
        **fields,
    )


@pytest.mark.django_db
def test_the_dashboard_needs_a_session(anonymous):
    assert anonymous.get(DASHBOARD).status_code == 403
    assert anonymous.get("/api/about/").status_code == 403


@pytest.mark.django_db
def test_an_empty_manager_has_an_empty_dashboard(api):
    assert api.get(DASHBOARD).json() == {
        "servers": [],
        "storage_bytes": 0,
        "last_export_at": None,
        "recent_failures": [],
        "key_store": "file",
    }


@pytest.mark.django_db
def test_each_application_shows_its_backups_plans_failures_storage_and_health(
    api, admin
):
    web = make_application(admin, "web-1", "10.0.0.5")
    worker = make_application(
        admin,
        "worker",
        server=web.server,
        kind="compose",
        engine="docker",
        compose_service="worker",
        project_dir="/srv/app",
    )
    quiet = make_server(admin, "web-2", "10.0.0.6")
    ServerRepository().update(web.server, last_check_status="ok")
    ApplicationRepository().update(web, last_health=HEALTH, last_check_status="ok")
    older = backup(web, "older.dbs", size=100)
    BackupFileRepository().update(older, created_at=timezone.now() - timedelta(days=1))
    newest = backup(web, "newest.dbs", size=200)
    backup(web, "media.tar.gz", kind=BackupFile.Kind.ARCHIVE, size=50)
    gone = backup(web, "gone.dbs", size=1000)
    BackupFileRepository().update(gone, removed_at=timezone.now())
    BackupFileRepository().soft_delete(backup(web, "deleted.dbs", size=7))
    backup(worker, "worker.dbs", size=30)
    soon = timezone.now() + timedelta(hours=1)
    for name, when, enabled in (
        ("nightly", soon, True),
        ("later", soon + timedelta(days=1), True),
        ("off", timezone.now(), False),
    ):
        BackupPlanRepository().create(
            application=web,
            name=name,
            kind=BackupPlan.Kind.DBS,
            interval_minutes=1440,
            next_run_at=when,
            enabled=enabled,
        )
    service = ActivityService(admin)
    service.record(
        "backup.take", subject=web, status=audit.FAILED, error_code="ssh_unreachable"
    )
    old = service.record("backup.take", subject=web, status=audit.FAILED)
    AuditEvent.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - timedelta(days=8)
    )
    service.record(
        "server.check",
        subject=web.server,
        status=audit.FAILED,
        error_code="ssh_auth_failed",
    )

    body = api.get(DASHBOARD).json()

    first, second = body["servers"]
    assert set(first) == SERVER_KEYS
    assert (first["id"], first["name"], first["host"], first["check_status"]) == (
        str(web.server.pk),
        "web-1",
        "10.0.0.5",
        "ok",
    )
    assert [application["name"] for application in first["applications"]] == [
        "web-1",
        "worker",
    ]
    shown, compose = first["applications"]
    assert set(shown) == APPLICATION_KEYS
    assert (shown["id"], shown["kind"], shown["engine"], shown["check_status"]) == (
        str(web.pk),
        "host",
        "",
        "ok",
    )
    assert shown["last_backup"]["id"] == str(newest.pk)
    assert set(shown["last_backup"]) == {
        "id",
        "name",
        "size",
        "created_at",
        "validation",
    }
    assert shown["last_backup"]["validation"] == "structure_ok"
    assert shown["next_plan_run"].startswith(soon.strftime("%Y-%m-%dT%H:%M"))
    assert shown["failures_7d"] == 1
    assert shown["storage_bytes"] == 100 + 200 + 50 + 7
    assert shown["health"] == HEALTH
    assert (compose["id"], compose["kind"], compose["engine"]) == (
        str(worker.pk),
        "compose",
        "docker",
    )
    assert compose["last_backup"]["name"] == "worker.dbs"
    assert (compose["next_plan_run"], compose["failures_7d"]) == (None, 0)
    assert compose["storage_bytes"] == 30
    assert second == {
        "id": str(quiet.pk),
        "name": "web-2",
        "host": "10.0.0.6",
        "check_status": "unknown",
        "checked_at": None,
        "connection_state": "unknown",
        "last_seen_at": None,
        "applications": [],
    }
    assert body["storage_bytes"] == 387
    failures = body["recent_failures"]
    assert [entry["error_code"] for entry in failures] == [
        "ssh_auth_failed",
        "ssh_unreachable",
        "",
    ]
    assert set(failures[0]) == ACTIVITY_KEYS
    assert (failures[0]["server_name"], failures[0]["application"]) == ("web-1", None)
    assert (failures[1]["server"], failures[1]["application"]) == (
        str(web.server.pk),
        str(web.pk),
    )
    assert (failures[1]["server_name"], failures[1]["application_name"]) == (
        "web-1",
        "web-1",
    )


@pytest.mark.django_db
def test_an_application_is_listed_under_the_server_it_runs_on(api, admin):
    shared = make_server(admin, "host-a", "10.0.0.7")
    make_application(admin, "shop", server=shared)
    make_application(admin, "blog", server=shared)
    make_application(admin, "api", "10.0.0.8")
    removed = make_application(admin, "old", server=shared)
    ApplicationRepository().soft_delete(removed)

    servers = {
        server["name"]: [application["name"] for application in server["applications"]]
        for server in api.get(DASHBOARD).json()["servers"]
    }

    assert servers == {"api": ["api"], "host-a": ["blog", "shop"]}


@pytest.mark.django_db
def test_the_last_export_is_the_newest_successful_one(api):
    audit.record("manager.export", target="first.dbs")
    newest = audit.record("manager.export", target="second.dbs")
    audit.record("manager.export", target="failed.dbs", status=audit.FAILED)

    exported = api.get(DASHBOARD).json()["last_export_at"]

    assert exported.startswith(newest.finished_at.strftime("%Y-%m-%dT%H:%M:%S"))
    assert api.get("/api/about/").json()["last_export_at"] == exported


@pytest.mark.django_db
def test_about_names_the_version_and_where_the_data_lives(api, data_dir, settings):
    body = api.get("/api/about/").json()

    assert body == {
        "version": dbs.__version__,
        "data_dir": str(data_dir),
        "database": body["database"],
        "backups_dir": settings.BACKUP_STORAGE_DIR,
        "last_export_at": None,
        "key_store": "file",
    }
    assert body["database"].startswith(f"{connection.vendor}:")


@pytest.mark.django_db
def test_a_key_kept_in_the_keychain_is_named_on_the_dashboard(api, settings):
    settings.DBS_MANAGER_KEY_STORE = "keychain"

    assert api.get(DASHBOARD).json()["key_store"] == "keychain"
    assert api.get("/api/about/").json()["key_store"] == "keychain"
