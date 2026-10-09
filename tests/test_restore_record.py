"""Restoring a backup the project already holds in DBS_BACKUP_DIR, from the panel."""

from io import StringIO

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client

from dbs.models import AuditEvent, BackupRecord
from tests.testapp.models import Author

PASS = "record-pass-phrase"


@pytest.fixture
def panel(db, settings):
    settings.DBS_SETUP_WIZARD = False
    client = Client()
    client.force_login(User.objects.create_superuser("root", "root@example.com", "pw"))
    return client


@pytest.fixture
def stored(tmp_path, settings, db):
    settings.DBS_BACKUP_DIR = str(tmp_path)
    Author.objects.create(name="Ada")
    path = tmp_path / "stored.dbs"
    call_command(
        "dbs_backup", str(path), passphrase=PASS, kdf_time=1, kdf_memory=8192, stdout=StringIO()
    )
    Author.objects.all().delete()
    return BackupRecord.objects.get(filename="stored.dbs")


def url(record):
    return f"/admin/dbs/backuprecord/{record.pk}/restore/"


def test_the_restore_page_opens_with_dry_run_ticked(panel, stored):
    response = panel.get(url(stored))

    assert response.status_code == 200
    assert b'name="dry_run"' in response.content and b"checked" in response.content


def test_a_dry_run_changes_nothing(panel, stored):
    response = panel.post(url(stored), {"passphrase": PASS, "dry_run": "on"}, follow=True)

    assert b"Dry run" in response.content
    assert not Author.objects.exists()
    event = AuditEvent.objects.get(action="backup.restore")
    assert event.data["dry_run"] is True and event.data["file"] == "stored.dbs"


def test_a_real_restore_needs_the_file_name_typed(panel, stored):
    refused = panel.post(url(stored), {"passphrase": PASS})
    restored = panel.post(
        url(stored), {"passphrase": PASS, "confirm": "stored.dbs"}, follow=True
    )

    assert refused.status_code == 200 and b"Type stored.dbs" in refused.content
    assert b"Restored" in restored.content
    assert Author.objects.get().name == "Ada"


def test_a_record_outside_the_backup_directory_is_a_404(panel, stored, tmp_path, settings):
    settings.DBS_BACKUP_DIR = str(tmp_path / "elsewhere")

    assert panel.get(url(stored)).status_code == 404


def test_a_record_held_off_site_is_a_404(panel, db):
    record = BackupRecord.objects.create(filename="remote.dbs", location="/srv/remote.dbs")

    assert panel.get(url(record)).status_code == 404
