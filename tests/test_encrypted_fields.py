"""Credentials stored in the database are encrypted under a SECRET_KEY-derived key."""

import pytest

from dbs.crypto.secrets import decrypt_secret, encrypt_secret, is_encrypted, read_secret
from dbs.exceptions import ConfigurationError, InvalidPassphrase
from dbs.models import AuthMethod, BackupTarget


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


@pytest.mark.django_db
def test_a_target_stores_its_password_encrypted():
    target = BackupTarget.objects.create(
        name="offsite",
        host="backups.example.com",
        username="deploy",
        auth_method=AuthMethod.PASSWORD,
        known_hosts="/home/deploy/.ssh/known_hosts",
        secret_password="hunter2",
    )
    target.refresh_from_db()

    assert target.secret_password.startswith("dbs1:")
    assert "hunter2" not in target.secret_password
    assert target.secret("secret_password") == "hunter2"
    assert not target.has_unreadable_secret()


@pytest.mark.django_db
def test_resaving_does_not_encrypt_twice():
    target = BackupTarget.objects.create(
        name="offsite",
        host="backups.example.com",
        username="deploy",
        auth_method=AuthMethod.PASSWORD,
        known_hosts="/known_hosts",
        secret_password="hunter2",
    )
    target.refresh_from_db()
    target.notes = "touched"
    target.save()
    target.refresh_from_db()

    assert target.secret("secret_password") == "hunter2"


@pytest.mark.django_db
def test_an_unreadable_credential_is_reported_rather_than_raised(settings):
    settings.SECRET_KEY_FALLBACKS = []
    target = BackupTarget.objects.create(
        name="offsite",
        host="backups.example.com",
        username="deploy",
        auth_method=AuthMethod.PASSWORD,
        known_hosts="/known_hosts",
        secret_password="hunter2",
    )
    target.refresh_from_db()

    settings.SECRET_KEY = "a-completely-different-key"
    assert target.secret("secret_password") is None
    assert target.has_unreadable_secret()


@pytest.mark.django_db
def test_ssh_target_carries_the_decrypted_password():
    target = BackupTarget.objects.create(
        name="offsite",
        host="backups.example.com",
        username="deploy",
        port=2222,
        remote_dir="/var/backups",
        auth_method=AuthMethod.PASSWORD,
        known_hosts="/known_hosts",
        secret_password="hunter2",
    )
    target.refresh_from_db()

    ssh = target.ssh_target()
    assert ssh.host == "backups.example.com"
    assert ssh.port == 2222
    assert ssh.password == "hunter2"
    assert ssh.use_agent is False
    assert ssh.host_key_policy == "reject-unknown"
