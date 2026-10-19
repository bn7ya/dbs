"""Regressions for the findings the 0.3.0 security review raised."""

import io

import pytest
from django.contrib.auth.models import User
from django.test import Client

from dbs.crypto.secrets import looks_sealed
from dbs.models import (
    AuditEvent,
    BackupRecord,
    Lockout,
    SecurityPolicy,
    SessionEvent,
)
from dbs.security import detector, guard
from dbs.security.features import client_address, ip_prefix
from dbs.security.sessions import REAUTH_FLAG

UNREACHABLE = 2.0

PANEL = "/admin/dbs/"
SETUP = "/admin/dbs/panel/setup/"
GUARD = "/admin/dbs/panel/guard/"
RESTORE = "/admin/dbs/backuprecord/restore/"

CONFIGURE = {
    "level": "balanced",
    "expected_networks": "",
    "trusted_networks": "127.0.0.0/8",
    "notify_emails": "",
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


def strict(trusted=""):
    policy = SecurityPolicy.load()
    policy.trusted_networks = trusted
    policy.learning_logins = 0
    policy.save()
    return policy


@pytest.mark.django_db
def test_a_session_cannot_vouch_for_its_own_new_network(panel):
    policy = strict()
    policy.logout_threshold = UNREACHABLE
    policy.save()

    first = panel.post(GUARD, "{}", content_type="application/json").json()
    second = panel.post(GUARD, "{}", content_type="application/json").json()

    assert "network" in " ".join(first["reasons"])
    assert "network" in " ".join(second["reasons"]), (
        "the second request in the same session must not treat the first as "
        "having established the network"
    )
    recorded = list(SessionEvent.objects.order_by("created_at", "id"))
    assert [event.features["new_ip_prefix"] for event in recorded[-2:]] == [1.0, 1.0]


@pytest.mark.django_db
def test_a_flagged_session_cannot_go_on_to_restore(panel):
    session = panel.session
    session[REAUTH_FLAG] = True
    session.save()

    upload = io.BytesIO(b"anything")
    upload.name = "x.dbs"
    response = panel.post(RESTORE, {"backup": upload})

    assert response.status_code == 302
    assert "login" in response["Location"]


@pytest.mark.django_db
def test_a_flagged_session_can_still_read(panel):
    session = panel.session
    session[REAUTH_FLAG] = True
    session.save()

    assert panel.get(PANEL).status_code == 200


@pytest.mark.django_db
def test_download_refuses_a_path_outside_the_backup_directory(panel, tmp_path, settings):
    settings.DBS_BACKUP_DIR = str(tmp_path / "backups")
    secret = tmp_path / "settings.py"
    secret.write_text("SECRET_KEY = 'leak-me'")
    record = BackupRecord.objects.create(filename="x.dbs", location=str(secret))

    response = panel.get(f"/admin/dbs/backuprecord/{record.pk}/download/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_download_serves_a_file_inside_the_backup_directory(panel, tmp_path, settings):
    directory = tmp_path / "backups"
    directory.mkdir()
    settings.DBS_BACKUP_DIR = str(directory)
    (directory / "good.dbs").write_bytes(b"DBSCON01payload")
    record = BackupRecord.objects.create(
        filename="good.dbs", location=str(directory / "good.dbs")
    )

    response = panel.get(f"/admin/dbs/backuprecord/{record.pk}/download/")

    assert response.status_code == 200
    assert b"".join(response.streaming_content) == b"DBSCON01payload"


@pytest.mark.django_db
def test_a_traversing_location_cannot_climb_out(panel, tmp_path, settings):
    directory = tmp_path / "backups"
    directory.mkdir()
    settings.DBS_BACKUP_DIR = str(directory)
    (tmp_path / "settings.py").write_text("SECRET_KEY = 'leak-me'")
    record = BackupRecord.objects.create(
        filename="x.dbs", location="../settings.py"
    )

    assert record.local_path() is None
    assert panel.get(f"/admin/dbs/backuprecord/{record.pk}/download/").status_code == 404


@pytest.mark.django_db
def test_the_catalogue_is_not_editable(panel):
    record = BackupRecord.objects.create(filename="x.dbs", location="")

    panel.post(
        f"/admin/dbs/backuprecord/{record.pk}/change/",
        {"filename": "y.dbs", "location": "/etc/passwd", "note": "edited"},
    )

    record.refresh_from_db()
    assert record.location == ""
    assert record.filename == "x.dbs"


@pytest.mark.django_db
def test_a_blanket_trusted_network_is_refused(panel):
    response = panel.post(SETUP, dict(CONFIGURE, trusted_networks="0.0.0.0/0"))

    assert response.status_code == 200
    assert b"too much of the internet" in response.content
    assert SecurityPolicy.load().trusted_networks == "127.0.0.0/8"


@pytest.mark.django_db
def test_a_blanket_network_is_ignored_even_if_it_reaches_the_database(panel):
    policy = strict(trusted="0.0.0.0/0")

    assert not guard.is_trusted("203.0.113.9", policy)


@pytest.mark.django_db
def test_a_malformed_network_is_reported_not_swallowed(panel):
    response = panel.post(SETUP, dict(CONFIGURE, trusted_networks="not-a-network"))

    assert response.status_code == 200
    assert b"is not a network" in response.content


@pytest.mark.django_db
def test_a_malformed_notification_address_is_reported(panel):
    response = panel.post(SETUP, dict(CONFIGURE, notify_emails="not-an-address"))

    assert response.status_code == 200
    assert not SecurityPolicy.load().notify_emails


@pytest.mark.django_db
def test_a_lockout_stops_requests_outside_the_admin_too(panel, root):
    Lockout.objects.create(user=root, reason="testing")

    response = panel.get("/elsewhere/")

    assert response.status_code == 302
    assert "login" in response["Location"]


@pytest.mark.django_db
def test_a_form_encoded_guard_post_does_not_crash(panel):
    response = panel.post(GUARD, {"anything": "here"})

    assert response.status_code == 200
    assert response.json()["action"] in ("continue", "reauth", "logout")


@pytest.mark.django_db
def test_a_superuser_who_is_not_staff_is_not_bounced_in_a_loop(db):
    user = User.objects.create_superuser("ghost", "g@example.com", "pw")
    user.is_staff = False
    user.save()
    client = Client()
    client.force_login(user)

    response = client.get("/admin/dbs/")

    assert response.status_code != 302 or "setup" not in response["Location"]


def test_forwarded_for_counts_back_from_the_proxy(rf, settings):
    settings.DBS_TRUST_FORWARDED_FOR = True
    settings.DBS_TRUSTED_PROXIES = ["127.0.0.0/8"]
    request = rf.get("/admin/dbs/", HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.7")

    assert client_address(request) == "203.0.113.7"

    settings.DBS_TRUSTED_PROXIES = ["127.0.0.0/8", "203.0.113.0/24"]
    assert client_address(request) == "1.2.3.4"


def test_forwarded_for_is_ignored_by_default(rf):
    request = rf.get("/admin/dbs/", HTTP_X_FORWARDED_FOR="1.2.3.4")

    assert client_address(request) == "127.0.0.1"


def test_a_plaintext_that_looks_encrypted_is_not_mistaken_for_ciphertext():
    assert not looks_sealed("dbs1:this is really a password")
    assert not looks_sealed("dbs1:")


def test_a_password_beginning_with_the_prefix_still_round_trips():
    from dbs.crypto.secrets import read_secret
    from dbs.models import SecretField

    stored = SecretField().get_prep_value("dbs1:not actually sealed")

    assert read_secret(stored) == "dbs1:not actually sealed"


@pytest.mark.django_db
def test_a_failed_login_is_recorded_and_counted(client):
    client.post("/admin/login/", {"username": "root", "password": "wrong"})

    assert AuditEvent.objects.filter(action="auth.failed", succeeded=False).exists()


@pytest.mark.django_db
def test_expected_networks_add_risk_when_the_request_is_outside_them(panel):
    policy = strict()
    policy.expected_networks = "203.0.113.0/24"
    policy.save()

    body = panel.post(GUARD, "{}", content_type="application/json").json()

    assert any("expects logins from" in reason for reason in body["reasons"])


def test_ip_prefix_groups_neighbours_and_ignores_nonsense():
    assert ip_prefix("203.0.113.9") == ip_prefix("203.0.113.200") == "203.0.113.0/24"
    assert ip_prefix("203.0.114.9") != ip_prefix("203.0.113.9")
    assert ip_prefix("nonsense") == ""
    assert ip_prefix("") == ""
