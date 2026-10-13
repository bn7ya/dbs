"""The DBS control panel mounted inside the Django admin."""

import io

import pytest
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import Client

from dbs.models import AuditEvent, BackupRecord
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
        "scheduling",
        "manager",
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
def test_the_panel_has_no_sftp_targets_or_console(panel):
    assert panel.get("/admin/dbs/backuptarget/").status_code == 404
    assert panel.get("/admin/dbs/backuptarget/1/console/").status_code == 404
    assert panel.get(f"{WIKI}targets/").status_code == 404
    page = panel.get(PANEL).content
    assert b"SFTP" not in page and b"console" not in page.lower()
    assert b"pulls them" in page


@pytest.mark.django_db
def test_taking_a_backup_offers_no_push(panel):
    response = panel.get(CREATE)

    assert b'name="destination"' not in response.content
    assert b"Push to" not in response.content


@pytest.fixture
def backup_dir(tmp_path, settings):
    settings.DBS_BACKUP_DIR = str(tmp_path / "backups")
    return tmp_path / "backups"


def take_backup(panel):
    response = panel.post(CREATE, {"database": "default", "note": "nightly"}, follow=True)
    return response, BackupRecord.objects.order_by("-pk").first()


@pytest.mark.django_db
def test_taking_a_backup_writes_it_to_the_backup_folder_and_offers_it(
    panel, backup_dir, inline_jobs
):
    Author.objects.create(name="Linus")

    response, record = take_backup(panel)

    assert response.redirect_chain[-1][0].startswith("/admin/dbs/backuprecord/jobs/")
    assert b"Wrote" in response.content and b"verified" in response.content
    path = backup_dir / record.filename
    assert record.local_path() == str(path)
    assert record.note == "nightly" and record.created_by.username == "root"
    event = AuditEvent.objects.get(action="backup.create")
    assert event.status == "succeeded" and event.target_name == record.filename
    assert event.data["size"] == path.stat().st_size == record.size_bytes
    download = f"/admin/dbs/backuprecord/{record.pk}/download/".encode()
    assert download in response.content

    served = panel.get(download.decode())

    assert served["Content-Disposition"].startswith("attachment;")
    assert b"".join(served.streaming_content) == path.read_bytes()
    assert path.read_bytes()[:8] == b"DBSCON01"


@pytest.mark.django_db
def test_without_a_backup_folder_the_panel_says_so_and_takes_nothing(panel, settings):
    settings.DBS_BACKUP_DIR = None

    page = panel.get(CREATE)
    posted = panel.post(CREATE, {"database": "default", "note": ""}, follow=True)

    assert b"Set <code>DBS_BACKUP_DIR</code>" in page.content
    assert b"did not start" in posted.content
    assert not AuditEvent.objects.filter(action="backup.create").exists()


@pytest.mark.django_db
def test_a_second_backup_waits_for_the_first(panel, backup_dir, inline_jobs):
    from dbs import jobs

    running = jobs.Runner().take()
    try:
        response = panel.post(CREATE, {"database": "default", "note": ""}, follow=True)
    finally:
        running.release()

    assert b"did not start" in response.content and b"running" in response.content
    assert not BackupRecord.objects.exists()


@pytest.mark.django_db
def test_a_dry_run_restore_changes_nothing(panel, backup_dir, inline_jobs):
    author = Author.objects.create(name="Linus")
    book = Book.objects.create(title="Kernel", author=author)
    book.cover.save("k.bin", ContentFile(b"KERNELBYTES"), save=True)
    _, record = take_backup(panel)
    Book.objects.all().delete()
    Author.objects.all().delete()

    upload = io.BytesIO((backup_dir / record.filename).read_bytes())
    upload.name = "backup.dbs"
    response = panel.post(RESTORE, {"backup": upload, "dry_run": "on"}, follow=True)

    assert response.status_code == 200
    assert b"Dry run" in response.content
    assert not Author.objects.exists()
    assert sorted(path.name for path in backup_dir.iterdir()) == [record.filename]


@pytest.mark.django_db
def test_a_real_restore_brings_the_rows_back(panel, backup_dir, inline_jobs):
    author = Author.objects.create(name="Linus")
    book = Book.objects.create(title="Kernel", author=author)
    book.cover.save("k.bin", ContentFile(b"KERNELBYTES"), save=True)
    _, record = take_backup(panel)
    Book.objects.all().delete()
    Author.objects.all().delete()

    upload = io.BytesIO((backup_dir / record.filename).read_bytes())
    upload.name = "backup.dbs"
    response = panel.post(RESTORE, {"backup": upload}, follow=True)

    assert b"Restored" in response.content
    assert Book.objects.get(title="Kernel").author.name == "Linus"
    restored = AuditEvent.objects.get(action="backup.restore")
    assert restored.succeeded and restored.target_name == "backup.dbs"
    assert restored.data["records"] >= 2 and restored.data["dry_run"] is False


@pytest.mark.django_db
def test_an_upload_over_the_limit_is_refused(panel, settings):
    settings.DBS_MAX_UPLOAD_BYTES = 16
    upload = io.BytesIO(b"x" * 64)
    upload.name = "big.dbs"

    response = panel.post(RESTORE, {"backup": upload}, follow=True)

    assert b"byte limit" in response.content


@pytest.mark.django_db
def test_a_corrupt_upload_reports_instead_of_crashing(panel, backup_dir, inline_jobs):
    upload = io.BytesIO(b"not a container at all")
    upload.name = "junk.dbs"

    response = panel.post(RESTORE, {"backup": upload}, follow=True)

    assert response.status_code == 200
    assert b"Restore failed" in response.content
    assert AuditEvent.objects.filter(action="backup.restore", succeeded=False).exists()
    assert list(backup_dir.iterdir()) == []


@pytest.mark.django_db
def test_downloading_a_record_with_no_file_is_a_404(panel):
    record = BackupRecord.objects.create(filename="gone.dbs", location="/nowhere/gone.dbs")

    assert panel.get(f"/admin/dbs/backuprecord/{record.pk}/download/").status_code == 404


@pytest.mark.django_db
def test_staff_without_superuser_see_nothing(db):
    staff = User.objects.create_user("clerk", "c@example.com", "pw", is_staff=True)
    client = Client()
    client.force_login(staff)

    for path in (PANEL, CREATE, RESTORE, WIKI, "/admin/dbs/backupschedule/"):
        assert client.get(path).status_code in (403, 404), path
