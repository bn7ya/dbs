from __future__ import annotations

import time
from urllib.parse import parse_qs, urlsplit

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.backups.services import BackupService
from dbs.manager.common import tickets
from tests.manager.servers.support import PASSWORD
from tests.manager.support import logged

LIST = "/api/backups/"
CONTENT = b"-- PostgreSQL database dump\n"
LOCMEM_CLOCK = "django.core.cache.backends.locmem.time"


@pytest.fixture
def sealed(admin, server):
    return BackupService(admin).upload(server.pk, SimpleUploadedFile("db.sql", CONTENT))


def link(api, backup, password=PASSWORD):
    body = {"account_password": password} if password is not None else {}
    return api.post(f"{LIST}{backup.pk}/download/", body, format="json")


def content(response) -> bytes:
    return b"".join(response.streaming_content)


@pytest.mark.django_db
def test_a_django_dbs_backup_downloads_without_a_password(api, taken):
    backup = taken()

    direct = api.get(f"{LIST}{backup.pk}/download/")
    linked = link(api, backup, password=None)

    assert direct.status_code == 200
    assert linked.json() == {"url": f"{LIST}{backup.pk}/download/"}
    assert linked["Cache-Control"] == "no-store"


@pytest.mark.django_db
def test_a_file_the_manager_sealed_needs_the_password_to_download(api, sealed):
    direct = api.get(f"{LIST}{sealed.pk}/download/")
    asked = link(api, sealed, password=None)

    for response in (direct, asked):
        assert response.status_code == 400
        assert response.json()["error"]["fields"] == {"account_password": ["required"]}
    assert logged("backup.download") == []


@pytest.mark.django_db
def test_a_wrong_password_is_refused_and_logged(api, admin, sealed):
    response = link(api, sealed, password="wrong")

    assert response.json()["error"]["code"] == "invalid_password"
    [entry] = logged("backup.download")
    assert (entry.status, entry.error_code, entry.actor) == (
        "failed",
        "invalid_password",
        admin,
    )


@pytest.mark.django_db
def test_the_password_buys_one_download_through_a_ticket(api, sealed):
    url = link(api, sealed).json()["url"]

    first = api.get(url)
    again = api.get(url)

    assert urlsplit(url).path == f"{LIST}{sealed.pk}/download/"
    assert first.status_code == 200 and content(first) == CONTENT
    assert again.status_code == 400
    assert again.json()["error"]["fields"] == {"account_password": ["required"]}
    assert [entry.status for entry in logged("backup.download")] == ["succeeded"]


@pytest.mark.django_db
def test_a_ticket_is_for_its_own_backup_and_account(api, admin, server, sealed):
    other = BackupService(admin).upload(server.pk, SimpleUploadedFile("b.sql", b"b"))
    ticket = parse_qs(urlsplit(link(api, sealed).json()["url"]).query)["ticket"][0]
    stranger = APIClient()
    stranger.force_login(UserRepository().create(username="omar", password=PASSWORD))

    elsewhere = api.get(f"{LIST}{other.pk}/download/", {"ticket": ticket})
    borrowed = stranger.get(f"{LIST}{sealed.pk}/download/", {"ticket": ticket})
    made_up = api.get(f"{LIST}{sealed.pk}/download/", {"ticket": "x" * 43})

    for response in (elsewhere, borrowed, made_up):
        assert response.status_code == 400
    assert content(api.get(f"{LIST}{sealed.pk}/download/", {"ticket": ticket})) == (
        CONTENT
    )


class AMinuteLater:
    @staticmethod
    def time():
        return time.time() + tickets.LIFETIME_SECONDS + 1


@pytest.mark.django_db
def test_a_ticket_lasts_a_minute(api, sealed, monkeypatch):
    url = link(api, sealed).json()["url"]
    monkeypatch.setattr(LOCMEM_CLOCK, AMinuteLater)

    response = api.get(url)

    assert response.status_code == 400
    assert tickets.LIFETIME_SECONDS == 60


@pytest.mark.django_db
def test_deleting_a_backup_needs_the_password(api, admin, server, taken):
    backup = taken()

    asked = api.delete(f"{LIST}{backup.pk}/")
    wrong = api.delete(
        f"{LIST}{backup.pk}/", {"account_password": "wrong"}, format="json"
    )
    listed = api.get(LIST, {"server": server.pk}).json()["count"]
    deleted = api.delete(
        f"{LIST}{backup.pk}/", {"account_password": PASSWORD}, format="json"
    )

    assert asked.json()["error"]["fields"] == {"account_password": ["required"]}
    assert wrong.json()["error"]["code"] == "invalid_password"
    assert listed == 1
    assert deleted.status_code == 204
    assert [(entry.status, entry.error_code) for entry in logged("backup.delete")] == [
        ("succeeded", ""),
        ("failed", "invalid_password"),
    ]
