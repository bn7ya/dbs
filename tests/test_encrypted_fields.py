"""Credentials stored in the database are encrypted under a SECRET_KEY-derived key."""

import pytest

from dbs.crypto.secrets import decrypt_secret, encrypt_secret, is_encrypted, read_secret
from dbs.exceptions import ConfigurationError, InvalidPassphrase


def test_round_trip():
    token = encrypt_secret("hunter2")
    assert is_encrypted(token)
    assert "hunter2" not in token
    assert decrypt_secret(token) == "hunter2"


def test_each_write_uses_a_fresh_nonce():
    assert encrypt_secret("same") != encrypt_secret("same")


def test_a_tampered_token_is_refused():
    token = encrypt_secret("hunter2")
    flipped = token[:-6] + ("A" if token[-6] != "A" else "B") + token[-5:]
    with pytest.raises(InvalidPassphrase):
        decrypt_secret(flipped)


def test_a_truncated_token_is_refused():
    with pytest.raises(InvalidPassphrase):
        decrypt_secret("dbs1:AAAA")


def test_plaintext_is_not_mistaken_for_a_credential():
    assert not is_encrypted("hunter2")
    with pytest.raises(InvalidPassphrase):
        decrypt_secret("hunter2")


def test_read_secret_passes_empty_values_through():
    assert read_secret("") is None
    assert read_secret(None) is None


def test_rotation_reads_through_the_fallbacks(settings):
    settings.SECRET_KEY = "first"
    settings.SECRET_KEY_FALLBACKS = []
    token = encrypt_secret("hunter2")

    settings.SECRET_KEY = "second"
    settings.SECRET_KEY_FALLBACKS = ["first"]
    assert decrypt_secret(token) == "hunter2"

    settings.SECRET_KEY_FALLBACKS = []
    with pytest.raises(InvalidPassphrase):
        decrypt_secret(token)


def test_encrypting_without_a_secret_key_is_refused(settings):
    settings.SECRET_KEY = ""
    settings.SECRET_KEY_FALLBACKS = []
    with pytest.raises(ConfigurationError):
        encrypt_secret("hunter2")
