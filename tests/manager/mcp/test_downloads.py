from __future__ import annotations

import stat

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from dbs.manager.backups.models import BackupFile
from dbs.manager.backups.services import BackupService
from dbs.manager.mcp.tools import SEALED_DOWNLOAD
from tests.manager.backups.support import BackupHost
from tests.manager.servers.support import connecting_to
from tests.manager.support import logged

CONNECT = "dbs.manager.servers.services.connection_service.connect"


@pytest.fixture
def host(monkeypatch):
    found = BackupHost(content=b"DBS stand-in")
    monkeypatch.setattr(CONNECT, connecting_to(found))
    return found


@pytest.mark.django_db(transaction=True)
def test_a_saved_backup_is_readable_by_its_owner_alone(
    mcp, admin, host, make_server, tmp_path
):
    make_server(name="shop")
    mcp("take_backups", servers=["shop"])
    backup = BackupFile.objects.get()

    saved = mcp("download_backup", backup=str(backup.pk), path=str(tmp_path))
    again = mcp("download_backup", backup=str(backup.pk), path=str(tmp_path))

    target = tmp_path / backup.name
    assert saved.ok, saved.text
    assert target.read_bytes() == b"DBS stand-in"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert not again.ok and "already exists" in again.text
    assert target.read_bytes() == b"DBS stand-in"


@pytest.mark.django_db
def test_a_file_the_manager_keeps_encrypted_is_never_saved(
    mcp, admin, make_server, tmp_path
):
    server = make_server(name="shop")
    uploaded = BackupService(admin).upload(
        server.pk, SimpleUploadedFile("db.sql", b"-- dump\n")
    )
    here = tmp_path / "here"
    here.mkdir()

    refused = mcp("download_backup", backup=str(uploaded.pk), path=str(here))

    assert not refused.ok and refused.text == SEALED_DOWNLOAD
    assert list(here.iterdir()) == []
    assert logged("backup.download") == []
