"""Learning mutes the anomaly model for a new account; it never switches enforcement off."""

from datetime import timedelta
from io import StringIO

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from dbs.models import Lockout, SecurityPolicy, SessionEvent
from dbs.security import detector, guard, telemetry

SETUP = "/admin/dbs/panel/setup/"
GUARD = "/admin/dbs/panel/guard/"

CONFIGURE = {
    "level": "balanced",
    "expected_networks": "",
    "trusted_networks": "127.0.0.0/8",
    "notify_emails": "",
}

NEW_NETWORK_AND_BROWSER = 0.55


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


def policy(*, learning, warn, logout):
    current = SecurityPolicy.load()
    current.trusted_networks = ""
    current.learning_logins = learning
    current.warn_threshold = warn
    current.logout_threshold = logout
    current.save()
    return current


def model_says(monkeypatch, value):
    monkeypatch.setattr(detector.IsolationForestDetector, "score", lambda self, user, values: value)


def poll(client):
    return client.post(GUARD, "{}", content_type="application/json").json()


def sessions(user, count, *, days_ago):
    moment = timezone.now() - timedelta(days=days_ago)
    for index in range(count):
        SessionEvent.objects.create(
            user=user, session_key_hash=f"old-session-{index}", features={}
        )
    SessionEvent.objects.filter(user=user, session_key_hash__startswith="old-session-").update(
        created_at=moment
    )


@pytest.mark.django_db
def test_learning_mutes_the_anomaly_model(panel, monkeypatch):
    model_says(monkeypatch, 1.0)
    policy(learning=500, warn=0.9, logout=0.95)

    assert poll(panel)["action"] == "continue"


@pytest.mark.django_db
def test_the_same_model_score_logs_out_once_learning_is_over(panel, root, monkeypatch):
    model_says(monkeypatch, 1.0)
    policy(learning=0, warn=0.9, logout=0.95)

    assert poll(panel)["action"] == "logout"
    assert Lockout.objects.filter(user=root).exists()


@pytest.mark.django_db
def test_learning_keeps_the_rules_and_the_logout_threshold(panel, root, monkeypatch):
    model_says(monkeypatch, 0.0)
    policy(learning=500, warn=0.3, logout=NEW_NETWORK_AND_BROWSER - 0.05)

    body = poll(panel)

    assert body["action"] == "logout"
    assert any("network is new" in reason for reason in body["reasons"])
    assert Lockout.objects.filter(user=root).exists()


@pytest.mark.django_db
def test_learning_keeps_the_warn_threshold(panel, monkeypatch):
    model_says(monkeypatch, 0.0)
    policy(learning=500, warn=NEW_NETWORK_AND_BROWSER - 0.05, logout=2.0)

    assert poll(panel)["action"] == "reauth"


@pytest.mark.django_db
def test_a_replacement_detector_is_not_muted_while_learning(panel, settings):
    settings.DBS_ANOMALY_DETECTOR = "tests.test_guard_learning.AlwaysAlarmed"
    policy(learning=500, warn=0.9, logout=0.95)

    assert poll(panel)["action"] == "logout"


class AlwaysAlarmed:
    def score(self, user, values):
        return 1.0


@pytest.mark.django_db
def test_a_dormant_admin_does_not_return_to_learning_after_a_purge(root, settings):
    settings.DBS_SECURITY_RETENTION_DAYS = 90
    current = policy(learning=10, warn=0.6, logout=0.85)
    sessions(root, 12, days_ago=200)
    assert not guard._still_learning(root, current)

    call_command("dbs", "security", "purge", stdout=StringIO())

    assert not telemetry.recorded_requests().filter(user=root).exists()
    assert telemetry.sessions_seen(root) == 12
    assert not guard._still_learning(root, current)


@pytest.mark.django_db
def test_repeated_purges_keep_adding_to_the_count(root):
    sessions(root, 3, days_ago=200)
    telemetry.purge(90)
    SessionEvent.objects.create(user=root, session_key_hash="later", features={})
    SessionEvent.objects.filter(session_key_hash="later").update(
        created_at=timezone.now() - timedelta(days=100)
    )

    telemetry.purge(90)

    assert telemetry.sessions_seen(root) == 4
    assert SessionEvent.objects.filter(kind=telemetry.SESSION_COUNT).count() == 1


@pytest.mark.django_db
def test_a_session_that_spans_the_cutoff_is_counted_once(root):
    SessionEvent.objects.create(user=root, session_key_hash="ongoing", features={})
    SessionEvent.objects.filter(session_key_hash="ongoing").update(
        created_at=timezone.now() - timedelta(days=200)
    )
    SessionEvent.objects.create(user=root, session_key_hash="ongoing", features={})

    telemetry.purge(90)

    assert telemetry.sessions_seen(root) == 1


@pytest.mark.django_db
def test_the_session_count_carries_no_telemetry(root):
    sessions(root, 2, days_ago=200)

    telemetry.purge(90)

    counter = SessionEvent.objects.get(kind=telemetry.SESSION_COUNT)
    assert counter.remote_addr == ""
    assert counter.ip_prefix == ""
    assert counter.latitude is None
    assert counter.features == {"sessions": 2}


@pytest.mark.django_db
def test_reset_baseline_starts_learning_again(root):
    current = policy(learning=10, warn=0.6, logout=0.85)
    sessions(root, 12, days_ago=200)
    telemetry.purge(90)

    call_command("dbs", "security", "reset-baseline", "root", stdout=StringIO())

    assert telemetry.sessions_seen(root) == 0
    assert guard._still_learning(root, current)
