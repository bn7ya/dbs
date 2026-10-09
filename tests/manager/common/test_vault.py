from __future__ import annotations

import secrets

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from dbs.manager.vault import (
    HEADER_BYTES,
    KEY_ID_BYTES,
    VaultError,
    seal,
    seal_text,
    unseal,
    unseal_text,
)


def new_key() -> str:
    return secrets.token_urlsafe(32)


def using(*keys):
    return override_settings(
        SECRET_KEY=keys[0] if keys else "", SECRET_KEY_FALLBACKS=list(keys[1:])
    )


def key_id(token: bytes) -> bytes:
    return token[HEADER_BYTES - KEY_ID_BYTES : HEADER_BYTES]


def test_a_sealed_value_opens_again():
    token = seal_text("ssh-password", context="servers.password")

    assert b"ssh-password" not in token
    assert unseal_text(token, context="servers.password") == "ssh-password"


def test_a_sealed_value_opens_from_a_memoryview():
    token = seal(b"\x00binary\xff", context="servers.private_key")

    assert unseal(memoryview(token), context="servers.private_key") == b"\x00binary\xff"


def test_the_same_value_seals_differently_each_time():
    assert seal_text("same", context="c") != seal_text("same", context="c")


def test_a_value_does_not_open_under_another_context():
    token = seal_text("ssh-password", context="servers.password")

    with pytest.raises(VaultError):
        unseal_text(token, context="servers.private_key")


@pytest.mark.parametrize("position", [0, 1, HEADER_BYTES, HEADER_BYTES + 12, -1])
def test_a_tampered_byte_is_refused(position):
    token = bytearray(seal_text("ssh-password", context="servers.password"))
    token[position] ^= 0x01

    with pytest.raises(VaultError):
        unseal(bytes(token), context="servers.password")


def test_something_the_vault_did_not_seal_is_refused():
    with pytest.raises(VaultError):
        unseal(b"short", context="servers.password")


def test_rotation_keeps_old_values_open_and_seals_new_ones_with_the_new_key():
    old, new = new_key(), new_key()
    with using(old):
        sealed_before = seal_text("kept", context="c")

    with using(new, old):
        assert unseal_text(sealed_before, context="c") == "kept"
        sealed_after = seal_text("fresh", context="c")

    assert key_id(sealed_after) != key_id(sealed_before)
    with using(new):
        assert unseal_text(sealed_after, context="c") == "fresh"


def test_a_value_sealed_with_a_key_no_longer_listed_is_refused():
    with using(new_key()):
        token = seal_text("orphaned", context="c")

    with (
        using(new_key()),
        pytest.raises(VaultError, match="no longer"),
    ):
        unseal_text(token, context="c")


def test_no_secret_key_is_a_configuration_error():
    with using(), pytest.raises(ImproperlyConfigured):
        seal_text("anything", context="c")


def test_the_vault_key_is_derived_from_the_secret_key_and_never_equals_it():
    from dbs.manager.vault import _keys

    with using("first-secret", "older-secret"):
        derived = _keys()

    assert len(derived) == 2 and all(len(key) == 32 for key in derived)
    assert b"first-secret" not in derived
