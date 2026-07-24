"""The optional admin UI: download a backup and upload/restore it."""

import io

import pytest
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import Client

from tests.testapp.models import Author, Book

PASS = "ui-pass-phrase"


@pytest.fixture
def admin_client(db):
    user = User.objects.create_superuser("root", "root@example.com", "pw")
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_non_staff_is_denied(client):
    # Anonymous users are redirected away from the backup view.
    response = client.get("/dbs/backup/")
    assert response.status_code in (302, 403)


@pytest.mark.django_db
def test_download_then_upload_restore(admin_client):
    author = Author.objects.create(name="Linus")
    book = Book.objects.create(title="Kernel", author=author)
    book.cover.save("k.bin", ContentFile(b"KERNELBYTES"), save=True)

    # Download a backup through the UI.
    response = admin_client.post("/dbs/backup/", {"passphrase": PASS, "passphrase2": PASS})
    assert response.status_code == 200
    assert response["Content-Disposition"].startswith("attachment;")
    container = response.content
    assert container[:8] == b"DBSCON01"

    # Wipe, then restore by uploading the file back through the UI.
    Book.objects.all().delete()
    Author.objects.all().delete()

    upload = io.BytesIO(container)
    upload.name = "backup.dbs"
    response = admin_client.post("/dbs/restore/", {"backup": upload, "passphrase": PASS})
    assert response.status_code == 200
    assert b"Restored" in response.content
    assert Book.objects.get(title="Kernel").author.name == "Linus"


@pytest.mark.django_db
def test_download_rejects_mismatched_passphrase(admin_client):
    response = admin_client.post("/dbs/backup/", {"passphrase": "a", "passphrase2": "b"})
    assert response.status_code == 200
    assert b"do not match" in response.content


@pytest.mark.django_db
def test_upload_larger_than_limit_is_rejected(admin_client, settings):
    settings.DBS_MAX_UPLOAD_BYTES = 16
    upload = io.BytesIO(b"x" * 64)
    upload.name = "big.dbs"
    response = admin_client.post("/dbs/restore/", {"backup": upload, "passphrase": "p"})
    assert response.status_code == 200
    assert b"byte limit" in response.content
