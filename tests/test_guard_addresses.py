"""Client-supplied addresses may only add risk: X-Forwarded-For counts only from known proxies."""

import pytest
from django.contrib.auth.models import User
from django.contrib.sessions.backends.db import SessionStore

from dbs import upgrade
from dbs.models import SecurityPolicy, SessionEvent
from dbs.security import guard
from dbs.security.checks import check_session_guard
from dbs.security.features import client_address, observe_request

PROXIES = ["10.0.0.0/8"]


def ids(messages):
    return {message.id for message in messages}


@pytest.fixture
def behind_proxies(settings):
    settings.DBS_TRUST_FORWARDED_FOR = True
    settings.DBS_TRUSTED_PROXIES = PROXIES
    return settings


def test_a_direct_client_cannot_forge_its_address(rf, behind_proxies):
    request = rf.get("/admin/", HTTP_X_FORWARDED_FOR="10.1.1.1", REMOTE_ADDR="203.0.113.9")

    assert client_address(request) == "203.0.113.9"


def test_the_right_most_untrusted_hop_is_the_client(rf, behind_proxies):
    request = rf.get(
        "/admin/",
        HTTP_X_FORWARDED_FOR="198.51.100.7, 203.0.113.5, 10.0.0.3",
        REMOTE_ADDR="10.0.0.2",
    )

    assert client_address(request) == "203.0.113.5"


def test_a_chain_of_trusted_proxies_resolves_to_its_origin(rf, behind_proxies):
    request = rf.get("/admin/", HTTP_X_FORWARDED_FOR="10.0.0.9, 10.0.0.3", REMOTE_ADDR="10.0.0.2")

    assert client_address(request) == "10.0.0.9"


def test_the_header_is_refused_without_trusted_proxies(rf, settings):
    settings.DBS_TRUST_FORWARDED_FOR = True
    request = rf.get("/admin/", HTTP_X_FORWARDED_FOR="10.1.1.1", REMOTE_ADDR="203.0.113.9")

    assert client_address(request) == "203.0.113.9"


def test_a_proxy_count_from_older_versions_trusts_nothing(rf, settings):
    settings.DBS_TRUST_FORWARDED_FOR = True
    settings.DBS_TRUSTED_PROXIES = 1
    request = rf.get("/admin/", HTTP_X_FORWARDED_FOR="10.1.1.1", REMOTE_ADDR="203.0.113.9")

    assert client_address(request) == "203.0.113.9"


def test_a_blanket_proxy_network_is_refused(rf, settings):
    settings.DBS_TRUST_FORWARDED_FOR = True
    settings.DBS_TRUSTED_PROXIES = ["0.0.0.0/0"]
    request = rf.get("/admin/", HTTP_X_FORWARDED_FOR="10.1.1.1", REMOTE_ADDR="203.0.113.9")

    assert client_address(request) == "203.0.113.9"


@pytest.mark.parametrize("forwarded", ["203.0.113.5, unknown", "203.0.113.5, ", ""])
def test_an_unreadable_hop_makes_the_address_unknown(rf, behind_proxies, forwarded):
    request = rf.get("/admin/", HTTP_X_FORWARDED_FOR=forwarded, REMOTE_ADDR="10.0.0.2")

    assert client_address(request) == ""


@pytest.mark.parametrize("peer", ["", "not-an-address", "999.1.1.1"])
def test_an_unreadable_peer_is_unknown(rf, peer):
    request = rf.get("/admin/", REMOTE_ADDR=peer)

    assert client_address(request) == ""


@pytest.mark.parametrize(
    "hop, expected",
    [("203.0.113.5:4711", "203.0.113.5"), ("[2001:db8::1]:443", "2001:db8::1")],
)
def test_a_hop_with_a_port_is_still_read(rf, behind_proxies, hop, expected):
    request = rf.get("/admin/", HTTP_X_FORWARDED_FOR=hop, REMOTE_ADDR="10.0.0.2")

    assert client_address(request) == expected


@pytest.mark.django_db
def test_an_unknown_address_never_matches_a_network():
    policy = SecurityPolicy.load()
    policy.trusted_networks = "10.0.0.0/8"
    policy.expected_networks = "10.0.0.0/8"
    policy.save()

    assert not guard.is_trusted("", policy)
    assert not guard._within("", policy.expected_networks)
    assert not guard._within("garbage", policy.expected_networks)


@pytest.mark.django_db
def test_an_unknown_address_reads_as_a_new_network(rf):
    user = User.objects.create_superuser("root", "root@example.com", "pw")
    SessionEvent.objects.create(user=user, session_key_hash="earlier", ip_prefix="", features={})
    request = rf.get("/admin/", REMOTE_ADDR="")
    request.user = user
    request.session = {}

    observation, address, _, _ = observe_request(user, request, "view")

    assert address == ""
    assert observation.new_ip_prefix


@pytest.mark.django_db
def test_an_unknown_address_adds_risk_and_says_so(rf):
    user = User.objects.create_superuser("root", "root@example.com", "pw")
    policy = SecurityPolicy.load()
    policy.expected_networks = "10.0.0.0/8"
    policy.save()
    request = rf.get("/admin/", REMOTE_ADDR="")
    request.user = user
    request.session = SessionStore()

    verdict = guard.evaluate(request)

    assert any("could not be determined" in reason for reason in verdict.reasons)
    assert any("expects logins from" in reason for reason in verdict.reasons)


def test_the_system_check_warns_when_no_proxy_is_named(settings):
    settings.DBS_TRUST_FORWARDED_FOR = True

    assert "dbs.security.W001" in ids(check_session_guard())

    settings.DBS_TRUSTED_PROXIES = PROXIES
    assert "dbs.security.W001" not in ids(check_session_guard())


def test_the_system_check_is_quiet_by_default():
    assert "dbs.security.W001" not in ids(check_session_guard())


@pytest.mark.django_db
def test_the_upgrade_step_names_the_new_proxy_setting(settings):
    step = upgrade.ForwardedFor()
    assert step.check().level == upgrade.OK

    settings.DBS_TRUST_FORWARDED_FOR = True
    settings.DBS_TRUSTED_PROXIES = 2
    reported = step.check()
    assert reported.level == upgrade.WARN
    assert "DBS_TRUSTED_PROXIES" in reported.remedy

    settings.DBS_TRUSTED_PROXIES = ()
    assert step.check().level == upgrade.WARN

    settings.DBS_TRUSTED_PROXIES = PROXIES
    assert step.check().level == upgrade.OK
