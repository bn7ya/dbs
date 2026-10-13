"""A flagged session can read, but cannot change anything or take a copy of the data."""

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from dbs.models import AnomalyEvent, BackupRecord, KnownLocation, SecurityPolicy, SessionEvent
from dbs.security import detector
from dbs.security.sessions import REAUTH_FLAG

SETUP = "/admin/dbs/panel/setup/"
GUARD = "/admin/dbs/panel/guard/"
PANEL = "/admin/dbs/"
ADD_USER = "/admin/auth/user/add/"
ADD_GROUP = "/admin/auth/group/add/"
ADD_LOCATION = "/admin/dbs/knownlocation/add/"
PASSWORD_CHANGE = "/admin/password_change/"
CONTRIB_BACKUP = "/dbs/backup/"

UNREACHABLE = 2.0

CONFIGURE = {
    "level": "balanced",
    "expected_networks": "",
    "trusted_networks": "127.0.0.0/8",
    "notify_emails": "",
}

NEW_SUPERUSER = {
    "username": "mallory",
    "password1": "a-long-enough-password-1",
    "password2": "a-long-enough-password-1",
    "usable_password": "true",
}


@pytest.fixture(autouse=True)
def clean_detector():
    detector.forget()
    yield
    detector.forget()


@pytest.fixture
def root(db):
    return User.objects.create_superuser("root", "root@example.com", "pw")


@pytest.fixture
def panel(root):
    client = Client()
    client.force_login(root)
    client.post(SETUP, CONFIGURE)
    return client


def flag(client):
    session = client.session
    session[REAUTH_FLAG] = True
    session.save()


def refused(response):
    return response.status_code in (302, 401) and "login" in response.get("Location", "login")


@pytest.fixture
def stored_backup(tmp_path, settings):
    directory = tmp_path / "backups"
    directory.mkdir()
    settings.DBS_BACKUP_DIR = str(directory)
    (directory / "good.dbs").write_bytes(b"DBSCON01payload")
    return BackupRecord.objects.create(filename="good.dbs", location=str(directory / "good.dbs"))


@pytest.mark.django_db
def test_a_flagged_session_cannot_create_a_superuser(panel):
    flag(panel)

    response = panel.post(ADD_USER, NEW_SUPERUSER)

    assert refused(response)
    assert not User.objects.filter(username="mallory").exists()


@pytest.mark.django_db
def test_a_flagged_session_cannot_change_groups(panel):
    flag(panel)

    response = panel.post(ADD_GROUP, {"name": "ops"})

    assert refused(response)
    assert not Group.objects.filter(name="ops").exists()


@pytest.mark.django_db
def test_a_flagged_session_cannot_post_anywhere_in_the_admin(panel, root):
    flag(panel)

    response = panel.post(
        ADD_LOCATION,
        {"user": root.pk, "label": "home", "latitude": 1, "longitude": 1, "radius_km": 5},
    )

    assert refused(response)
    assert not KnownLocation.objects.exists()


@pytest.mark.django_db
def test_a_flagged_session_cannot_download_a_backup(panel, stored_backup):
    flag(panel)

    response = panel.get(f"/admin/dbs/backuprecord/{stored_backup.pk}/download/")

    assert refused(response)
    assert not getattr(response, "streaming", False)


@pytest.mark.django_db
def test_a_flagged_session_cannot_export_through_the_contrib_views(panel):
    flag(panel)

    response = panel.post(CONTRIB_BACKUP, {"passphrase": "p", "passphrase2": "p"})

    assert refused(response)
    assert not response.has_header("Content-Disposition")


@pytest.mark.django_db
def test_a_flagged_session_can_still_read_and_poll(panel):
    flag(panel)

    assert panel.get(PANEL).status_code == 200
    assert panel.post(GUARD, "{}", content_type="application/json").status_code == 200


@pytest.mark.django_db
def test_an_unflagged_session_can_still_change_accounts(panel):
    response = panel.post(ADD_GROUP, {"name": "ops"})

    assert response.status_code == 302
    assert Group.objects.filter(name="ops").exists()


@pytest.mark.django_db
def test_the_warning_refuses_the_request_that_raised_it(panel):
    policy = SecurityPolicy.load()
    policy.trusted_networks = ""
    policy.learning_logins = 0
    policy.warn_threshold = 0.0
    policy.logout_threshold = UNREACHABLE
    policy.save()

    response = panel.post(ADD_GROUP, {"name": "ops"})

    assert refused(response)
    assert not Group.objects.filter(name="ops").exists()
    assert AnomalyEvent.objects.filter(action_taken="warn").exists()


@pytest.mark.parametrize("path", [ADD_USER, ADD_GROUP, PASSWORD_CHANGE])
@pytest.mark.django_db
def test_account_changes_are_scored_as_high_risk(panel, path):
    panel.post(path, {})

    newest = SessionEvent.objects.order_by("-id").first()
    assert newest.features["action_risk"] == 1.0


@pytest.mark.django_db
def test_downloads_are_scored_as_downloads_even_without_a_post(panel, stored_backup):
    panel.get(f"/admin/dbs/backuprecord/{stored_backup.pk}/download/")

    risks = {event.features["action_risk"] for event in SessionEvent.objects.all()}
    assert 0.7 in risks
