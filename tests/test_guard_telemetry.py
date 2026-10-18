"""What the guard keeps, for how long, and how an idle or misplaced guard is handled."""

import sys
import time
from datetime import timedelta
from io import StringIO

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from dbs import audit, upgrade
from dbs.models import AnomalyEvent, AuditEvent, SecurityPolicy, SessionEvent
from dbs.security import detector, telemetry
from dbs.security.checks import REPAIR, check_session_guard
from dbs.security.networks import address_digest, stored_prefix
from dbs.security.sessions import LAST_ACTIVE

SETUP = "/admin/dbs/panel/setup/"
GUARD = "/admin/dbs/panel/guard/"
PANEL = "/admin/dbs/"

GUARD_MIDDLEWARE = "dbs.security.middleware.DBSSecurityMiddleware"

CONFIGURE = {
    "level": "balanced",
    "expected_networks": "",
    "trusted_networks": "127.0.0.0/8",
    "notify_emails": "",
}


def ids(messages):
    return {message.id for message in messages}


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


@pytest.fixture
def purge_due(monkeypatch):
    monkeypatch.setattr(telemetry, "_last_purge", None)


def age(queryset, days):
    queryset.update(created_at=timezone.now() - timedelta(days=days))


def idle_for(client, minutes):
    session = client.session
    session[LAST_ACTIVE] = int(timezone.now().timestamp()) - minutes * 60
    session.save()


def idle_timeout(minutes):
    policy = SecurityPolicy.load()
    policy.idle_timeout_minutes = minutes
    policy.save()


@pytest.mark.django_db
def test_a_request_stores_the_network_and_a_keyed_hash_never_the_address(panel):
    panel.get(PANEL, REMOTE_ADDR="203.0.113.77")

    event = SessionEvent.objects.order_by("-id").first()
    assert event.ip_prefix == "203.0.113.0/24"
    assert event.remote_addr == address_digest("203.0.113.77")
    assert "203.0.113.77" not in event.remote_addr


@pytest.mark.django_db
def test_an_anomaly_records_only_the_network(panel):
    policy = SecurityPolicy.load()
    policy.learning_logins = 0
    policy.warn_threshold = 0.0
    policy.logout_threshold = 2.0
    policy.save()

    panel.post(GUARD, "{}", content_type="application/json", REMOTE_ADDR="203.0.113.77")

    assert AnomalyEvent.objects.get().remote_addr == "203.0.113.0/24"


def test_ipv6_is_kept_to_a_48():
    assert stored_prefix("2001:db8:1:2:3::9") == "2001:db8:1::/48"
    assert stored_prefix("nonsense") == ""


def test_the_address_hash_is_keyed_to_the_project(settings):
    first = address_digest("203.0.113.77")
    assert first == address_digest("203.0.113.77")
    assert len(first) == 64

    settings.SECRET_KEY = "another-project"
    assert address_digest("203.0.113.77") != first
    assert address_digest("") == ""


@pytest.mark.django_db
def test_old_telemetry_is_purged_once_a_day_on_its_own(panel, root, purge_due, monkeypatch):
    SessionEvent.objects.create(user=root, features={})
    AnomalyEvent.objects.create(user=root)
    kept = audit.record("backup.create", target="old.dbs")
    age(SessionEvent.objects.filter(session_key_hash=""), 200)
    age(AnomalyEvent.objects.all(), 200)
    age(AuditEvent.objects.filter(pk=kept.pk), 200)

    panel.get(PANEL)

    assert not telemetry.recorded_requests().filter(created_at__lt=timezone.now() - timedelta(days=90)).exists()
    assert not AnomalyEvent.objects.exists()
    assert AuditEvent.objects.filter(pk=kept.pk).exists()

    SessionEvent.objects.create(user=root, session_key_hash="later", features={})
    age(SessionEvent.objects.filter(session_key_hash="later"), 200)
    panel.get(PANEL)
    assert SessionEvent.objects.filter(session_key_hash="later").exists()

    monkeypatch.setattr(
        telemetry, "_last_purge", time.monotonic() - telemetry.PURGE_INTERVAL_SECONDS
    )
    panel.get(PANEL)
    assert not SessionEvent.objects.filter(session_key_hash="later").exists()


@pytest.mark.django_db
def test_a_failing_purge_never_fails_the_request(panel, purge_due, monkeypatch):
    def broken(days=None):
        raise RuntimeError("disk full")

    monkeypatch.setattr(telemetry, "purge", broken)

    assert panel.get(PANEL).status_code == 200


@pytest.mark.django_db
def test_the_purge_command_keeps_the_audit_trail_and_records_itself(root, settings):
    settings.DBS_SECURITY_RETENTION_DAYS = 30
    SessionEvent.objects.create(user=root, features={})
    age(SessionEvent.objects.all(), 60)
    old = audit.record("backup.create", target="old.dbs")
    age(AuditEvent.objects.filter(pk=old.pk), 60)
    out = StringIO()

    call_command("dbs", "security", "purge", stdout=out)

    assert AuditEvent.objects.filter(pk=old.pk).exists()
    entry = AuditEvent.objects.get(action="security.purge")
    assert entry.data == {"events": 1, "anomalies": 0, "retention_days": 30}
    assert "audit trail is kept" in out.getvalue()


@pytest.mark.django_db
def test_purge_coarsens_addresses_left_by_older_versions(root):
    SessionEvent.objects.create(user=root, remote_addr="203.0.113.9", features={})
    SessionEvent.objects.create(user=root, remote_addr="2001:db8::1", features={})
    AnomalyEvent.objects.create(user=root, remote_addr="203.0.113.9")

    telemetry.purge(90)

    stored = set(SessionEvent.objects.values_list("remote_addr", flat=True))
    assert stored == {address_digest("203.0.113.9"), address_digest("2001:db8::1")}
    assert AnomalyEvent.objects.get().remote_addr == "203.0.113.0/24"


@pytest.mark.django_db
def test_an_idle_session_is_ended(panel):
    idle_timeout(30)
    idle_for(panel, 31)

    response = panel.get(PANEL)

    assert response.status_code == 302
    assert "login" in response["Location"]
    assert "_auth_user_id" not in panel.session


@pytest.mark.django_db
def test_an_active_session_carries_on(panel):
    idle_timeout(30)
    idle_for(panel, 5)

    assert panel.get(PANEL).status_code == 200


@pytest.mark.django_db
def test_a_zero_idle_timeout_is_off(panel):
    idle_timeout(0)
    idle_for(panel, 60 * 24)

    assert panel.get(PANEL).status_code == 200


@pytest.mark.django_db
def test_the_guard_poll_is_not_activity_and_is_ended_when_idle(panel):
    idle_timeout(30)
    idle_for(panel, 10)
    before = panel.session[LAST_ACTIVE]

    panel.post(GUARD, "{}", content_type="application/json")
    assert panel.session[LAST_ACTIVE] == before

    idle_for(panel, 31)
    response = panel.post(GUARD, "{}", content_type="application/json")
    assert response.status_code == 401
    assert response.json()["action"] == "logout"


@pytest.mark.django_db
def test_a_page_view_counts_as_activity(panel):
    idle_timeout(30)
    idle_for(panel, 10)
    before = panel.session[LAST_ACTIVE]

    panel.get(PANEL)

    assert panel.session[LAST_ACTIVE] > before


def misplaced(settings):
    stack = [entry for entry in settings.MIDDLEWARE if entry != GUARD_MIDDLEWARE]
    stack.insert(1, GUARD_MIDDLEWARE)
    settings.MIDDLEWARE = stack


def test_the_guard_placed_before_authentication_is_reported(settings):
    assert "dbs.security.W002" not in ids(check_session_guard())

    misplaced(settings)

    assert "dbs.security.W002" in ids(check_session_guard())


@pytest.mark.django_db
def test_upgrade_does_not_call_a_misplaced_guard_active(settings):
    misplaced(settings)

    finding = upgrade.GuardMiddleware().check()

    assert finding.level == upgrade.WARN
    assert "active" not in finding.message
    assert "AuthenticationMiddleware" in finding.remedy


@pytest.fixture
def without_scikit_learn(monkeypatch):
    monkeypatch.setitem(sys.modules, "sklearn", None)
    monkeypatch.setitem(sys.modules, "sklearn.ensemble", None)


def test_a_scikit_learn_that_cannot_import_is_a_warning_naming_the_repair(without_scikit_learn):
    warnings = [message for message in check_session_guard() if message.id == "dbs.security.W003"]

    assert warnings
    assert warnings[0].hint == REPAIR == 'pip install --force-reinstall "django-dbs"'


def test_scikit_learn_is_not_demanded_without_the_guard(without_scikit_learn, settings):
    settings.MIDDLEWARE = [entry for entry in settings.MIDDLEWARE if entry != GUARD_MIDDLEWARE]

    assert "dbs.security.W003" not in ids(check_session_guard())


@pytest.mark.django_db
def test_the_rules_still_score_without_scikit_learn(panel, root, without_scikit_learn):
    policy = SecurityPolicy.load()
    policy.trusted_networks = ""
    policy.learning_logins = 0
    policy.warn_threshold = 0.5
    policy.logout_threshold = 2.0
    policy.save()

    body = panel.post(GUARD, "{}", content_type="application/json").json()

    assert body["action"] == "reauth"
    assert any("network is new" in reason for reason in body["reasons"])
    assert detector.IsolationForestDetector().score(root, {}) == 0.0


@pytest.mark.django_db
def test_the_command_reports_the_missing_model(without_scikit_learn):
    status, retrain = StringIO(), StringIO()

    call_command("dbs", "security", "status", stdout=status)
    call_command("dbs", "security", "retrain", stdout=retrain)

    assert REPAIR in status.getvalue()
    assert REPAIR in retrain.getvalue()
