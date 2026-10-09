from __future__ import annotations

import hashlib
import hmac
import secrets

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from dbs.manager.vault import fingerprint


def new_key() -> str:
    return secrets.token_urlsafe(32)


def using(*keys):
    return override_settings(
        SECRET_KEY=keys[0] if keys else "", SECRET_KEY_FALLBACKS=list(keys[1:])
    )


def test_the_same_data_fingerprints_the_same_and_other_data_does_not():
    with using(new_key()):
        first = fingerprint(b"API_KEY=one\n", context="envfiles.content")
        again = fingerprint(b"API_KEY=one\n", context="envfiles.content")
        other = fingerprint(b"API_KEY=two\n", context="envfiles.content")

    assert first == again
    assert first != other


def test_a_fingerprint_is_sixty_four_hex_characters():
    assert len(fingerprint(b"", context="c")) == 64
    int(fingerprint(b"x", context="c"), 16)


def test_a_fingerprint_is_not_a_plain_digest_of_the_data():
    data = b"PASSWORD=hunter2\n"

    assert (
        fingerprint(data, context="envfiles.content")
        != hashlib.sha256(data).hexdigest()
    )


def test_each_context_fingerprints_the_same_data_differently():
    assert fingerprint(b"same", context="envfiles.content") != fingerprint(
        b"same", context="other.content"
    )


def test_it_is_hmac_sha256_under_a_key_hkdf_derives_from_the_active_vault_key():
    active, older = new_key(), new_key()
    vault_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"django-dbs/manager-vault/v1",
    ).derive(active.encode())
    subkey = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"django-dbs/manager-vault/fingerprint\x00envfiles.content",
    ).derive(vault_key)

    with using(active, older):
        made = fingerprint(b"A=1\n", context="envfiles.content")

    assert made == hmac.new(subkey, b"A=1\n", hashlib.sha256).hexdigest()


def test_after_a_rotation_the_same_data_fingerprints_differently():
    old, new = new_key(), new_key()
    with using(old):
        before = fingerprint(b"A=1\n", context="envfiles.content")

    with using(new, old):
        after = fingerprint(b"A=1\n", context="envfiles.content")

    assert before != after


def test_no_vault_key_is_a_configuration_error():
    with using(), pytest.raises(ImproperlyConfigured):
        fingerprint(b"A=1\n", context="c")
