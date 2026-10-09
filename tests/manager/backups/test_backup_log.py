from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from dbs.manager.servers.exceptions import RemoteCommandFailed
from tests.manager.backups.support import ARCHIVED_PATHS, BackupHost
from tests.manager.servers.support import (
    BACKUP_PASSPHRASE,
    PASSWORD,
    body_line,
    connecting_to,
)

CONNECT = "dbs.manager.servers.services.connection_service.connect"
LIST = "/api/backups/"


@pytest.mark.django_db
def test_every_backup_action_is_logged_and_none_holds_a_secret(
    api, monkeypatch, server, private_key, run_jobs, taken
):
    backup = taken()
    api.post(
        f"{LIST}upload/",
        {"server": server.pk, "file": SimpleUploadedFile("db.sql", b"x")},
        format="multipart",
    )
    with run_jobs():
        api.post(f"{LIST}{backup.pk}/verify/")
    b"".join(api.get(f"{LIST}{backup.pk}/download/").streaming_content)
    api.delete(f"{LIST}{backup.pk}/")
    api.post(f"{LIST}{backup.pk}/undo-delete/")
    monkeypatch.setattr(
        CONNECT, connecting_to(BackupHost(failure=RemoteCommandFailed(output="exit 1")))
    )
    with run_jobs():
        api.post(f"{LIST}take/", {"server": server.pk})

    response = api.get("/api/activity/", {"server": server.pk, "page_size": 200})

    entries = [
        (entry["action"], entry["status"]) for entry in response.json()["results"]
    ]
    assert entries == [
        ("backup.take", "failed"),
        ("backup.undo_delete", "succeeded"),
        ("backup.delete", "succeeded"),
        ("backup.download", "succeeded"),
        ("backup.verify", "succeeded"),
        ("backup.upload", "succeeded"),
        ("backup.take", "succeeded"),
        ("server.create", "succeeded"),
    ]
    body = response.content.decode()
    for secret in (BACKUP_PASSPHRASE, body_line(private_key)):
        assert secret not in body


@pytest.mark.django_db
def test_every_plan_action_is_logged_and_none_holds_a_secret(
    api, server, host, private_key, run_jobs
):
    plan = api.post(
        "/api/backups/plans/",
        {"server": server.pk, "name": "django-dbs", "kind": "dbs", "keep": 1},
    ).json()
    api.patch(f"/api/backups/plans/{plan['id']}/", {"interval_minutes": 60})
    for _ in range(2):
        with run_jobs():
            api.post(f"/api/backups/plans/{plan['id']}/run/")
    api.delete(f"/api/backups/plans/{plan['id']}/")

    response = api.get("/api/activity/", {"server": server.pk, "page_size": 200})

    entries = [
        (entry["action"], entry["status"], entry["target"])
        for entry in response.json()["results"]
    ]
    assert entries == [
        ("plan.delete", "succeeded", "django-dbs"),
        ("backup.retention", "succeeded", "django-dbs"),
        ("backup.run", "succeeded", "django-dbs"),
        ("backup.run", "succeeded", "django-dbs"),
        ("plan.update", "succeeded", "django-dbs"),
        ("plan.create", "succeeded", "django-dbs"),
        ("server.create", "succeeded", "web-1"),
    ]
    body = response.content.decode()
    for secret in (BACKUP_PASSPHRASE, body_line(private_key)):
        assert secret not in body


@pytest.mark.django_db
def test_every_archive_action_is_logged_and_none_holds_a_secret(
    api, server, host, private_key, run_jobs
):
    plan = api.post(
        "/api/backups/plans/",
        {
            "server": str(server.pk),
            "name": "files",
            "kind": "archive",
            "paths": ARCHIVED_PATHS,
            "keep": 1,
            "account_password": PASSWORD,
        },
        format="json",
    ).json()
    for _ in range(2):
        with run_jobs():
            api.post(f"/api/backups/plans/{plan['id']}/run/")
    [backup] = api.get(LIST, {"server": server.pk}).json()["results"]
    with run_jobs():
        api.post(f"{LIST}{backup['id']}/verify/")
    b"".join(api.get(f"{LIST}{backup['id']}/download/").streaming_content)

    response = api.get("/api/activity/", {"server": server.pk, "page_size": 200})

    entries = [
        (entry["action"], entry["status"]) for entry in response.json()["results"]
    ]
    assert entries == [
        ("backup.download", "succeeded"),
        ("backup.verify", "succeeded"),
        ("backup.retention", "succeeded"),
        ("backup.run", "succeeded"),
        ("backup.run", "succeeded"),
        ("plan.create", "succeeded"),
        ("server.create", "succeeded"),
    ]
    body = response.content.decode()
    for secret in (BACKUP_PASSPHRASE, body_line(private_key), PASSWORD):
        assert secret not in body
