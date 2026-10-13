from __future__ import annotations

import base64
from urllib.parse import parse_qs, urlsplit

import pytest

from dbs.manager.accounts import totp

RFC_SECRET = base64.b32encode(b"12345678901234567890").decode().rstrip("=")


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (59, "287082"),
        (1111111109, "081804"),
        (1111111111, "050471"),
        (1234567890, "005924"),
        (2000000000, "279037"),
        (20000000000, "353130"),
    ],
)
def test_codes_match_the_rfc_6238_sha1_vectors(moment, expected):
    assert totp.code_at(RFC_SECRET, moment) == expected


def test_a_code_from_one_step_either_side_is_accepted():
    now = 1_700_000_000
    step = totp.step_at(now)

    for offset in (-1, 0, 1):
        code = totp.code_at(RFC_SECRET, now + offset * totp.PERIOD)
        assert totp.matching_step(RFC_SECRET, code, now) == step + offset


def test_a_code_two_steps_away_is_refused():
    now = 1_700_000_000

    assert (
        totp.matching_step(RFC_SECRET, totp.code_at(RFC_SECRET, now - 60), now) is None
    )
    assert (
        totp.matching_step(RFC_SECRET, totp.code_at(RFC_SECRET, now + 60), now) is None
    )


def test_a_step_already_used_is_never_matched_again():
    now = 1_700_000_000
    code = totp.code_at(RFC_SECRET, now)
    step = totp.matching_step(RFC_SECRET, code, now)

    assert totp.matching_step(RFC_SECRET, code, now, after=step) is None
    assert totp.matching_step(RFC_SECRET, code, now, after=step - 1) == step


@pytest.mark.parametrize("typed", ["", "12345", "1234567", "abcdef", "12 34 5x"])
def test_anything_but_six_digits_is_refused(typed):
    assert totp.matching_step(RFC_SECRET, typed, 59) is None


def test_spaces_inside_a_code_are_ignored():
    assert totp.matching_step(RFC_SECRET, "287 082", 59) == totp.step_at(59)


def test_a_new_secret_is_160_bits_of_base32():
    secret = totp.new_secret()

    assert len(totp.secret_bytes(secret)) == totp.SECRET_BYTES
    assert secret != totp.new_secret()


def test_the_provisioning_uri_names_the_account_and_the_issuer():
    uri = totp.provisioning_uri(RFC_SECRET, "sara", "DBS manager")
    parts = urlsplit(uri)
    query = parse_qs(parts.query)

    assert parts.scheme == "otpauth" and parts.netloc == "totp"
    assert parts.path == "/DBS%20manager%3Asara"
    assert query == {
        "secret": [RFC_SECRET],
        "issuer": ["DBS manager"],
        "algorithm": ["SHA1"],
        "digits": ["6"],
        "period": ["30"],
    }
