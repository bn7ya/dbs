"""Browser location as an anomaly signal: opt-in, add-only, impossible travel."""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone

from dbs.models import KnownLocation, SecurityPolicy, SessionEvent
from dbs.security import detector, geo
from dbs.security.features import FEATURE_NAMES, haversine_km, observe_request

GUARD = "/admin/dbs/panel/guard/"
SETUP = "/admin/dbs/panel/setup/"

CONFIGURE = {
    "level": "relaxed",
    "expected_networks": "",
    "trusted_networks": "127.0.0.0/8",
    "notify_emails": "",
}

RIYADH = {"latitude": 24.7136, "longitude": 46.6753, "accuracy": 30.0}
BERLIN = {"latitude": 52.52, "longitude": 13.405, "accuracy": 30.0}


@pytest.fixture
def root(db):
    return User.objects.create_superuser("root", "root@example.com", "pw")


@pytest.fixture
def panel(root):
    client = Client()
    client.force_login(root)
    client.post(SETUP, CONFIGURE)
    return client


def test_it_is_off_unless_the_setting_enables_it(settings):
    settings.DBS_GEOLOCATION = False
    assert not geo.enabled()
    assert geo.clean(RIYADH) is None

    settings.DBS_GEOLOCATION = True
    assert geo.enabled()
    assert geo.clean(RIYADH) is not None


def test_coordinates_are_rounded_before_storage(settings):
    settings.DBS_GEOLOCATION = True

    cleaned = geo.clean({"latitude": 24.713612345, "longitude": 46.675387654})

    assert cleaned["latitude"] == 24.71
    assert cleaned["longitude"] == 46.68


@pytest.mark.parametrize(
    "payload",
    [
        None,
        "not a dict",
        {},
        {"latitude": 91.0, "longitude": 0.0},
        {"latitude": 0.0, "longitude": 181.0},
        {"latitude": "nowhere", "longitude": 0.0},
    ],
)
def test_nonsense_from_the_browser_is_discarded(payload, settings):
    settings.DBS_GEOLOCATION = True
    assert geo.clean(payload) is None


def test_an_absurd_accuracy_is_dropped_but_the_fix_is_kept(settings):
    settings.DBS_GEOLOCATION = True

    cleaned = geo.clean(dict(RIYADH, accuracy=10_000_000))

    assert cleaned["accuracy"] is None
    assert cleaned["latitude"] == 24.71


def test_haversine_measures_a_known_distance():
    assert 4000 < haversine_km(
        (RIYADH["latitude"], RIYADH["longitude"]),
        (BERLIN["latitude"], BERLIN["longitude"]),
    ) < 4400


@pytest.mark.django_db
def test_the_feature_vector_keeps_its_width_without_a_location(rf, root):
    request = rf.get("/admin/dbs/")
    request.user = root
    request.session = {}

    observation, _, _, _ = observe_request(root, request, "view", None)

    assert observation.distance_km == 0.0
    assert observation.travel_kmh == 0.0
    assert len(FEATURE_NAMES) == 13


@pytest.mark.django_db
def test_a_recent_fix_far_away_reads_as_impossible_travel(rf, root, settings):
    settings.DBS_GEOLOCATION = True
    SessionEvent.objects.create(
        user=root,
        latitude=RIYADH["latitude"],
        longitude=RIYADH["longitude"],
        features={},
    )
    request = rf.get("/admin/dbs/")
    request.user = root
    request.session = {}

    observation, _, _, _ = observe_request(root, request, "view", geo.clean(BERLIN))

    assert observation.travel_kmh > 900


@pytest.mark.django_db
def test_impossible_travel_raises_the_rule_score():
    calm, _ = detector.rule_score({"travel_kmh": 5.0})
    flying, reasons = detector.rule_score({"travel_kmh": 3000.0})

    assert flying > calm
    assert any("km/h" in reason for reason in reasons)


@pytest.mark.django_db
def test_a_known_location_never_lowers_the_score(rf, root, settings):
    settings.DBS_GEOLOCATION = True
    KnownLocation.objects.create(
        user=root,
        latitude=RIYADH["latitude"],
        longitude=RIYADH["longitude"],
        radius_km=50,
    )
    request = rf.get("/admin/dbs/")
    request.user = root
    request.session = {}

    without, _, _, _ = observe_request(root, request, "view", None)
    at_home, _, _, _ = observe_request(root, request, "view", geo.clean(RIYADH))

    engine = detector.IsolationForestDetector()
    from dbs.security.features import build

    assert engine.score(root, build(at_home)) >= engine.score(root, build(without))


@pytest.mark.django_db
def test_a_declined_location_changes_nothing(panel, settings):
    settings.DBS_GEOLOCATION = True

    with_none = panel.post(
        GUARD, '{"location": null}', content_type="application/json"
    ).json()

    assert with_none["action"] == "continue"


@pytest.mark.django_db
def test_the_guard_stores_a_rounded_fix(panel, settings, root):
    settings.DBS_GEOLOCATION = True
    policy = SecurityPolicy.load()
    policy.collect_location = True
    policy.save()

    panel.post(
        GUARD,
        '{"location": {"latitude": 24.713612, "longitude": 46.675387}}',
        content_type="application/json",
    )

    event = SessionEvent.objects.filter(latitude__isnull=False).first()
    assert event is not None
    assert event.latitude == 24.71


@pytest.mark.django_db
def test_the_guard_ignores_a_fix_when_the_setting_is_off(panel, settings):
    settings.DBS_GEOLOCATION = False

    panel.post(
        GUARD,
        '{"location": {"latitude": 24.71, "longitude": 46.68}}',
        content_type="application/json",
    )

    assert not SessionEvent.objects.filter(latitude__isnull=False).exists()


@pytest.mark.django_db
def test_purge_drops_telemetry_past_the_retention_window(panel, settings):
    from io import StringIO

    from django.core.management import call_command

    settings.DBS_SECURITY_RETENTION_DAYS = 0
    panel.post(GUARD, "{}", content_type="application/json")
    assert SessionEvent.objects.exists()

    call_command("dbs", "security", "purge", stdout=StringIO())

    assert not SessionEvent.objects.filter(created_at__lt=timezone.now()).exists()
