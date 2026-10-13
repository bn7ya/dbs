"""The personal model refits off the request path, at most once per interval, on recent rows."""

import threading

import pytest
from django.contrib.auth.models import User
from django.test import Client

from dbs.models import SecurityPolicy, SessionEvent
from dbs.security import detector, synthetic
from dbs.security.features import FEATURE_NAMES

SETUP = "/admin/dbs/panel/setup/"
PANEL = "/admin/dbs/"

CONFIGURE = {
    "level": "balanced",
    "expected_networks": "",
    "trusted_networks": "127.0.0.0/8",
    "notify_emails": "",
}

HISTORY = 60


@pytest.fixture(autouse=True)
def clean_detector():
    detector.forget()
    yield
    detector.forget()


@pytest.fixture
def root(db):
    return User.objects.create_superuser("root", "root@example.com", "pw")


@pytest.fixture
def clock(monkeypatch):
    moment = {"now": 1000.0}
    monkeypatch.setattr(detector, "_clock", lambda: moment["now"])
    return moment


@pytest.fixture
def refits(monkeypatch):
    started = []

    def run_now(user_pk, generation):
        started.append(user_pk)
        detector.refit(user_pk, generation)

    monkeypatch.setattr(detector, "start_refit", run_now)
    return started


def history(user, count, seed=1):
    for row in synthetic.normal_rows(count, seed=seed):
        SessionEvent.objects.create(
            user=user, session_key_hash="earlier", features=dict(zip(FEATURE_NAMES, row))
        )


def typical():
    return dict(zip(FEATURE_NAMES, synthetic.typical_row()))


def request(user, engine):
    SessionEvent.objects.create(user=user, session_key_hash="now", features=typical())
    return engine.score(user, typical())


@pytest.mark.django_db
def test_a_burst_of_requests_refits_at_most_once(root, refits):
    history(root, HISTORY)
    client = Client()
    client.force_login(root)
    client.post(SETUP, CONFIGURE)
    policy = SecurityPolicy.load()
    policy.learning_logins = 0
    policy.save()

    for _ in range(30):
        assert client.get(PANEL).status_code == 200

    assert refits == [root.pk]


@pytest.mark.django_db
def test_the_request_does_not_wait_for_the_refit(root, monkeypatch):
    history(root, HISTORY)
    started = []
    monkeypatch.setattr(detector, "start_refit", lambda user_pk, generation: started.append(user_pk))
    engine = detector.IsolationForestDetector()

    first = request(root, engine)
    second = request(root, engine)

    assert started == [root.pk]
    assert detector.personal_model(root) is None
    assert 0.0 <= first <= 1.0 and 0.0 <= second <= 1.0


@pytest.mark.django_db
def test_the_last_fit_serves_until_the_interval_passes(root, refits, clock):
    history(root, HISTORY)
    engine = detector.IsolationForestDetector()
    request(root, engine)
    fitted = detector.personal_model(root)

    for _ in range(10):
        request(root, engine)
    assert detector.personal_model(root) is fitted
    assert len(refits) == 1

    clock["now"] += detector.REFIT_SECONDS
    request(root, engine)

    assert len(refits) == 2
    assert detector.personal_model(root) is not fitted


@pytest.mark.django_db
def test_enough_new_events_refit_before_the_interval(root, refits, clock, monkeypatch):
    monkeypatch.setattr(detector, "REFIT_EVENTS", 5)
    history(root, HISTORY)
    engine = detector.IsolationForestDetector()
    request(root, engine)

    for _ in range(6):
        request(root, engine)

    assert len(refits) == 2


@pytest.mark.django_db
def test_the_model_keeps_learning_from_the_newest_rows(root, refits, clock, monkeypatch):
    monkeypatch.setattr(detector, "WINDOW_ROWS", HISTORY)
    history(root, HISTORY)
    engine = detector.IsolationForestDetector()
    request(root, engine)
    first = detector._fits[root.pk]

    history(root, HISTORY * 2, seed=2)
    clock["now"] += detector.REFIT_SECONDS
    request(root, engine)
    second = detector._fits[root.pk]

    newest = SessionEvent.objects.order_by("-created_at").values_list("id", flat=True).first()
    assert second.newest_id == newest
    assert second.newest_id > first.newest_id
    assert second.rows == HISTORY


@pytest.mark.django_db
def test_an_account_without_enough_history_never_starts_a_refit(root, refits):
    history(root, 5)
    engine = detector.IsolationForestDetector()

    for _ in range(10):
        request(root, engine)

    assert refits == []
    assert detector.personal_model(root) is None


@pytest.mark.django_db
def test_forget_discards_a_refit_already_in_flight(root, monkeypatch):
    history(root, HISTORY)
    started = []
    monkeypatch.setattr(
        detector, "start_refit", lambda user_pk, generation: started.append(generation)
    )
    detector.IsolationForestDetector().score(root, typical())

    detector.forget()
    detector.refit(root.pk, started[0])

    assert root.pk not in detector._fits


@pytest.mark.django_db
def test_a_failed_refit_waits_for_the_interval(root, refits, clock, monkeypatch):
    history(root, HISTORY)

    def broken(user_pk):
        raise RuntimeError("database went away")

    monkeypatch.setattr(detector, "_fit", broken)
    engine = detector.IsolationForestDetector()

    for _ in range(5):
        request(root, engine)

    assert len(refits) == 1


def test_the_default_refit_runs_in_a_background_thread(monkeypatch):
    seen = {}
    done = threading.Event()

    def record(user_pk, generation):
        seen["thread"] = threading.current_thread()
        done.set()

    monkeypatch.setattr(detector, "refit", record)

    detector.start_refit(1, 0)

    assert done.wait(5)
    assert seen["thread"] is not threading.main_thread()
    assert seen["thread"].daemon
