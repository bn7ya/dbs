"""The DBS control panel mounted inside the Django admin."""

import io

import pytest
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import Client

from dbs.models import AuditEvent, BackupRecord, BackupTarget
from tests.testapp.models import Author, Book

PANEL = "/admin/dbs/"
SETUP = "/admin/dbs/panel/setup/"
CREATE = "/admin/dbs/backuprecord/create/"
RESTORE = "/admin/dbs/backuprecord/restore/"
WIKI = "/admin/dbs/panel/wiki/"

CONFIGURE = {
    "level": "relaxed",
    "expected_networks": "",
    "trusted_networks": "127.0.0.0/8",
    "notify_emails": "",
}

TARGET = {
    "name": "offsite",
    "host": "backups.example.com",
    "port": 22,
    "username": "deploy",
    "remote_dir": "/var/backups",
    "auth_method": "password",
    "key_filename": "",
    "known_hosts": "/home/deploy/.ssh/known_hosts",
    "connect_timeout": 30.0,
    "notes": "",
    "password": "hunter2",
    "key_material": "",
    "key_passphrase": "",
}


@pytest.fixture
def panel(db):
    user = User.objects.create_superuser("root", "root@example.com", "pw")
    client = Client()
    client.force_login(user)
    client.post(SETUP, CONFIGURE)
    return client


@pytest.mark.django_db
def test_the_panel_is_mounted_without_touching_urls(panel):
    response = panel.get(PANEL)

    assert response.status_code == 200
    assert b"DBS" in response.content


@pytest.mark.django_db
def test_the_panel_wears_the_admin_theme(panel):
    templates = {template.name for template in panel.get(PANEL).templates if template.name}

    assert "admin/dbs/app_index.html" in templates
    assert "admin/base_site.html" in templates


@pytest.mark.django_db
def test_every_wiki_page_renders(panel):
    assert panel.get(WIKI).status_code == 200
    for page in (
        "getting-started",
        "passphrases",
        "targets",
        "scheduling",
        "restore",
        "commands",
        "upgrading",
        "security",
        "privacy",
        "ai",
        "troubleshooting",
    ):
        assert panel.get(f"{WIKI}{page}/").status_code == 200, page


@pytest.mark.django_db
def test_an_unknown_wiki_page_is_a_404(panel):
    assert panel.get(f"{WIKI}not-a-page/").status_code == 404


@pytest.mark.django_db
def test_a_target_is_created_through_the_admin_with_its_password_encrypted(panel):
    response = panel.post("/admin/dbs/backuptarget/add/", TARGET)

    assert response.status_code == 302
    target = BackupTarget.objects.get(name="offsite")
    assert target.secret_password.startswith("dbs1:")
    assert target.secret("secret_password") == "hunter2"


@pytest.mark.django_db
def test_editing_a_target_without_retyping_keeps_the_password(panel):
    panel.post("/admin/dbs/backuptarget/add/", TARGET)
    target = BackupTarget.objects.get(name="offsite")

    panel.post(
        f"/admin/dbs/backuptarget/{target.pk}/change/",
        dict(TARGET, password="", notes="edited"),
    )

    target.refresh_from_db()
    assert target.notes == "edited"
    assert target.secret("secret_password") == "hunter2"


@pytest.mark.django_db
def test_a_target_needs_a_host_key_policy(panel):
    response = panel.post("/admin/dbs/backuptarget/add/", dict(TARGET, known_hosts=""))

    assert response.status_code == 200
    assert not BackupTarget.objects.exists()
    assert b"known_hosts" in response.content


@pytest.mark.django_db
def test_password_auth_needs_a_password(panel):
    response = panel.post("/admin/dbs/backuptarget/add/", dict(TARGET, password=""))

    assert response.status_code == 200
    assert not BackupTarget.objects.exists()


@pytest.mark.django_db
def test_taking_a_backup_downloads_it_and_records_it(panel):
    Author.objects.create(name="Linus")

    response = panel.post(CREATE, {"database": "default", "destination": "", "note": ""})

    assert response.status_code == 200
    assert response["Content-Disposition"].startswith("attachment;")
    assert response.content[:8] == b"DBSCON01"
    record = BackupRecord.objects.get()
    assert record.size_bytes == len(response.content)
    assert AuditEvent.objects.filter(action="backup.create").exists()


@pytest.mark.django_db
def test_a_dry_run_restore_changes_nothing(panel):
    author = Author.objects.create(name="Linus")
    book = Book.objects.create(title="Kernel", author=author)
    book.cover.save("k.bin", ContentFile(b"KERNELBYTES"), save=True)
    container = panel.post(
        CREATE, {"database": "default", "destination": "", "note": ""}
    ).content
    Book.objects.all().delete()
    Author.objects.all().delete()

    upload = io.BytesIO(container)
    upload.name = "backup.dbs"
    response = panel.post(RESTORE, {"backup": upload, "dry_run": "on"}, follow=True)

    assert response.status_code == 200
    assert b"Dry run" in response.content
    assert not Author.objects.exists()


@pytest.mark.django_db
def test_a_real_restore_brings_the_rows_back(panel):
    author = Author.objects.create(name="Linus")
    book = Book.objects.create(title="Kernel", author=author)
    book.cover.save("k.bin", ContentFile(b"KERNELBYTES"), save=True)
    container = panel.post(
        CREATE, {"database": "default", "destination": "", "note": ""}
    ).content
    Book.objects.all().delete()
    Author.objects.all().delete()

    upload = io.BytesIO(container)
    upload.name = "backup.dbs"
    response = panel.post(RESTORE, {"backup": upload}, follow=True)

    assert b"Restored" in response.content
    assert Book.objects.get(title="Kernel").author.name == "Linus"
    assert AuditEvent.objects.filter(action="backup.restore", succeeded=True).exists()


@pytest.mark.django_db
def test_an_upload_over_the_limit_is_refused(panel, settings):
    settings.DBS_MAX_UPLOAD_BYTES = 16
    upload = io.BytesIO(b"x" * 64)
    upload.name = "big.dbs"

    response = panel.post(RESTORE, {"backup": upload}, follow=True)

    assert b"byte limit" in response.content


@pytest.mark.django_db
def test_a_corrupt_upload_reports_instead_of_crashing(panel):
    upload = io.BytesIO(b"not a container at all")
    upload.name = "junk.dbs"

    response = panel.post(RESTORE, {"backup": upload}, follow=True)

    assert response.status_code == 200
    assert b"Restore failed" in response.content
    assert AuditEvent.objects.filter(action="backup.restore", succeeded=False).exists()


@pytest.mark.django_db
def test_downloading_a_record_with_no_file_is_a_404(panel):
    record = BackupRecord.objects.create(filename="gone.dbs", location="/nowhere/gone.dbs")

    assert panel.get(f"/admin/dbs/backuprecord/{record.pk}/download/").status_code == 404


@pytest.mark.django_db
def test_staff_without_superuser_see_nothing(db):
    staff = User.objects.create_user("clerk", "c@example.com", "pw", is_staff=True)
    client = Client()
    client.force_login(staff)

    for path in (PANEL, CREATE, RESTORE, WIKI, "/admin/dbs/backuptarget/"):
        assert client.get(path).status_code in (403, 404), path
