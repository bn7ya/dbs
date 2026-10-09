from datetime import timedelta

import pytest
from django.utils import timezone

import dbs
from dbs import audit
from dbs.manager.activity.services import ActivityService
from dbs.manager.backups.models import BackupFile, BackupPlan
from dbs.manager.backups.repositories import BackupFileRepository, BackupPlanRepository
from dbs.manager.servers.models import Server
from dbs.manager.servers.repositories import ServerRepository
from dbs.manager.servers.services import ServerService
from dbs.models import AuditEvent
from tests.manager.servers.support import host_key_line, private_key_text

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
    "created_at",
    "started_at",
    "finished_at",
}


def add_server(admin, name, host):
    return ServerService(admin).create(
        name=name,
        host=host,
        username="deploy",
        auth_method=Server.AuthMethod.KEY,
        private_key=private_key_text(),
        host_key=host_key_line(),
    )


def backup(server, name, kind=BackupFile.Kind.DBS, size=100, **fields):
    return BackupFileRepository().create(
        server=server,
        kind=kind,
        name=name,
        size=size,
        sha256="0" * 64,
        storage_path=f"{server.pk}/{name}",
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
    }


@pytest.mark.django_db
def test_each_server_shows_its_backups_plans_failures_storage_and_health(api, admin):
    web = add_server(admin, "web-1", "10.0.0.5")
    quiet = add_server(admin, "web-2", "10.0.0.6")
    ServerRepository().update(web, last_health=HEALTH, last_check_status="ok")
    older = backup(web, "older.dbs", size=100)
    BackupFileRepository().update(older, created_at=timezone.now() - timedelta(days=1))
    newest = backup(web, "newest.dbs", size=200)
    backup(web, "media.tar.gz", kind=BackupFile.Kind.ARCHIVE, size=50)
    gone = backup(web, "gone.dbs", size=1000)
    BackupFileRepository().update(gone, removed_at=timezone.now())
    BackupFileRepository().soft_delete(backup(web, "deleted.dbs", size=7))
    soon = timezone.now() + timedelta(hours=1)
    for name, when, enabled in (
        ("nightly", soon, True),
        ("later", soon + timedelta(days=1), True),
        ("off", timezone.now(), False),
    ):
        BackupPlanRepository().create(
            server=web,
            name=name,
            kind=BackupPlan.Kind.DBS,
            interval_minutes=1440,
            next_run_at=when,
            enabled=enabled,
        )
    service = ActivityService(admin)
    service.record(
        "backup.take", server=web, status=audit.FAILED, error_code="ssh_unreachable"
    )
    old = service.record("backup.take", server=web, status=audit.FAILED)
    AuditEvent.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - timedelta(days=8)
    )

    body = api.get(DASHBOARD).json()

    first, second = body["servers"]
    assert set(first) == SERVER_KEYS
    assert (first["name"], first["host"], first["check_status"]) == (
        "web-1",
        "10.0.0.5",
        "ok",
    )
    assert first["last_backup"]["id"] == str(newest.pk)
    assert set(first["last_backup"]) == {
        "id",
        "name",
        "size",
        "created_at",
        "validation",
    }
    assert first["last_backup"]["validation"] == "structure_ok"
    assert first["next_plan_run"].startswith(soon.strftime("%Y-%m-%dT%H:%M"))
    assert first["failures_7d"] == 1
    assert first["storage_bytes"] == 100 + 200 + 50 + 7
    assert first["health"] == HEALTH
    assert second == {
        "id": str(quiet.pk),
        "name": "web-2",
        "host": "10.0.0.6",
        "check_status": "unknown",
        "checked_at": None,
        "last_backup": None,
        "next_plan_run": None,
        "failures_7d": 0,
        "storage_bytes": 0,
        "health": None,
    }
    assert body["storage_bytes"] == 357
    failures = body["recent_failures"]
    assert [entry["error_code"] for entry in failures] == ["ssh_unreachable", ""]
    assert set(failures[0]) == ACTIVITY_KEYS
    assert failures[0]["server_name"] == "web-1"


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
    }
    assert body["database"].startswith("sqlite:")
