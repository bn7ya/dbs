"""The session guard: setup, authorization, anomaly scoring and auto-logout."""

from io import StringIO

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client

from dbs.models import AnomalyEvent, Lockout, SecurityPolicy, SessionEvent
from dbs.security import detector, guard

SETUP = "/admin/dbs/panel/setup/"
GUARD = "/admin/dbs/panel/guard/"
PANEL = "/admin/dbs/"

CONFIGURE = {
    "level": "balanced",
    "expected_networks": "",
    "trusted_networks": "127.0.0.0/8",
    "notify_emails": "",
}


@pytest.fixture(autouse=True)
def clean_models():
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


@pytest.mark.django_db
def test_an_unconfigured_superuser_is_sent_to_the_wizard(root):
    client = Client()
    client.force_login(root)

    response = client.get(PANEL)

    assert response.status_code == 302
    assert response["Location"] == SETUP
    assert client.get(SETUP).status_code == 200


@pytest.mark.django_db
def test_the_wizard_writes_the_policy_and_stops_redirecting(panel):
    policy = SecurityPolicy.load()
    assert policy.configured
    assert policy.trusted_networks == "127.0.0.0/8"
    assert policy.warn_threshold == 0.60
    assert panel.get(PANEL).status_code == 200


@pytest.mark.django_db
def test_each_security_level_sets_its_own_thresholds(root):
    client = Client()
    client.force_login(root)
    client.post(SETUP, dict(CONFIGURE, level="paranoid"))

    policy = SecurityPolicy.load()
    assert policy.level == "paranoid"
    assert policy.logout_threshold < 0.85
    assert policy.learning_logins == 0


@pytest.mark.django_db
def test_staff_who_are_not_superusers_cannot_reach_the_panel(db):
    staff = User.objects.create_user("clerk", "c@example.com", "pw", is_staff=True)
    client = Client()
    client.force_login(staff)

    assert client.get(PANEL).status_code == 404
    assert client.get(SETUP).status_code == 404
    assert client.post(GUARD, "{}", content_type="application/json").status_code == 404


@pytest.mark.django_db
def test_anonymous_visitors_are_redirected_to_the_login(client):
    response = client.get(PANEL)
    assert response.status_code == 302
    assert "login" in response["Location"]


@pytest.mark.django_db
def test_the_guard_reports_an_authorized_session(panel):
    response = panel.post(GUARD, "{}", content_type="application/json")

    body = response.json()
    assert response.status_code == 200
    assert body["authorized"] is True
    assert body["action"] == "continue"
    assert body["poll_after"] >= 1


@pytest.mark.django_db
def test_the_guard_only_accepts_post(panel):
    assert panel.get(GUARD).status_code == 405


@pytest.mark.django_db
def test_every_scored_request_is_recorded(panel):
    before = SessionEvent.objects.count()
    panel.post(GUARD, "{}", content_type="application/json")
    assert SessionEvent.objects.count() > before


@pytest.mark.django_db
def test_a_trusted_network_is_scored_but_never_enforced_against(panel, settings):
    settings.DBS_TRUSTED_NETWORKS = ["127.0.0.0/8"]
    policy = SecurityPolicy.load()
    policy.learning_logins = 0
    policy.warn_threshold = 0.0
    policy.logout_threshold = 0.0
    policy.save()

    body = panel.post(GUARD, "{}", content_type="application/json").json()

    assert body["action"] == "continue"
    assert SessionEvent.objects.exists()
    assert not Lockout.objects.exists()


@pytest.mark.django_db
def test_the_learning_period_records_without_enforcing(panel):
    policy = SecurityPolicy.load()
    policy.trusted_networks = ""
    policy.learning_logins = 500
    policy.warn_threshold = 0.0
    policy.logout_threshold = 0.0
    policy.save()

    body = panel.post(GUARD, "{}", content_type="application/json").json()

    assert body["action"] == "continue"
    assert not Lockout.objects.exists()


@pytest.mark.django_db
def test_a_blocking_score_ends_the_session(panel, root):
    policy = SecurityPolicy.load()
    policy.trusted_networks = ""
    policy.learning_logins = 0
    policy.warn_threshold = 0.0
    policy.logout_threshold = 0.0
    policy.save()

    response = panel.post(GUARD, "{}", content_type="application/json")

    assert response.json()["authorized"] is False
    assert response.json()["action"] == "logout"
    assert Lockout.objects.filter(user=root).exists()
    assert AnomalyEvent.objects.filter(user=root, action_taken="logout").exists()


@pytest.mark.django_db
def test_a_locked_out_account_cannot_use_the_panel(panel, root):
    Lockout.objects.create(user=root, reason="testing")

    response = panel.get(PANEL)

    assert response.status_code == 302
    assert "login" in response["Location"]


@pytest.mark.django_db
def test_unlock_from_the_command_line_restores_access(panel, root):
    Lockout.objects.create(user=root, reason="testing")
    out = StringIO()

    call_command("dbs", "security", "unlock", "root", stdout=out)

    assert not Lockout.objects.filter(user=root).exists()
    assert "can log in again" in out.getvalue()
    panel.force_login(root)
    assert panel.get(PANEL).status_code == 200


@pytest.mark.django_db
def test_unlock_needs_a_real_account(db):
    with pytest.raises(CommandError):
        call_command("dbs", "security", "unlock", "nobody", stdout=StringIO())
    with pytest.raises(CommandError):
        call_command("dbs", "security", "unlock", stdout=StringIO())


@pytest.mark.django_db
def test_enforcement_can_be_switched_off(panel, settings):
    settings.DBS_ANOMALY_ENFORCE = False
    policy = SecurityPolicy.load()
    policy.trusted_networks = ""
    policy.learning_logins = 0
    policy.logout_threshold = 0.0
    policy.warn_threshold = 0.0
    policy.save()

    body = panel.post(GUARD, "{}", content_type="application/json").json()

    assert body["authorized"] is True
    assert not Lockout.objects.exists()


@pytest.mark.django_db
def test_status_and_purge_report_what_they_did(panel, settings):
    settings.DBS_SECURITY_RETENTION_DAYS = 0
    panel.post(GUARD, "{}", content_type="application/json")
    status, purged = StringIO(), StringIO()

    call_command("dbs", "security", "status", stdout=status)
    call_command("dbs", "security", "purge", stdout=purged)

    assert "level" in status.getvalue()
    assert "Removed" in purged.getvalue()
    assert not SessionEvent.objects.exists()


@pytest.mark.django_db
def test_a_replacement_detector_is_honoured(panel, settings):
    settings.DBS_ANOMALY_DETECTOR = "tests.test_security_guard.AlwaysCalm"
    policy = SecurityPolicy.load()
    policy.trusted_networks = ""
    policy.learning_logins = 0
    policy.save()

    body = panel.post(GUARD, "{}", content_type="application/json").json()

    assert body["action"] == "continue"


class AlwaysCalm:
    def score(self, user, values):
        return 0.0


@pytest.mark.django_db
def test_trusted_network_matching_ignores_nonsense(panel):
    policy = SecurityPolicy.load()
    policy.trusted_networks = "not-a-network\n\n10.0.0.0/8"
    policy.save()

    assert guard.is_trusted("10.1.2.3", policy)
    assert not guard.is_trusted("192.0.2.1", policy)
    assert not guard.is_trusted("", policy)
    assert not guard.is_trusted("nonsense", policy)
