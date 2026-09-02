"""The backup passphrase DBS derives from Django's SECRET_KEY."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from dbs._cli import passphrase_source, resolve_passphrase, resolve_read_passphrase
from dbs.engine import create_backup, restore_backup
from dbs.exceptions import InvalidPassphrase
from dbs.keys import (
    candidate_passphrases,
    default_passphrase,
    derive_passphrase,
    with_passphrase,
)
from tests.testapp.models import Author

FAST = {"kdf_time": 1, "kdf_memory": 8192}


def test_derivation_is_stable_and_domain_separated(settings):
    settings.SECRET_KEY = "a-particular-secret"
    first = default_passphrase()
    assert first == default_passphrase()
    assert first != settings.SECRET_KEY
    assert settings.SECRET_KEY not in first


def test_a_different_secret_key_gives_a_different_passphrase():
    assert derive_passphrase("one") != derive_passphrase("two")


def test_fallbacks_are_offered_after_the_current_key(settings):
    settings.SECRET_KEY = "new"
    settings.SECRET_KEY_FALLBACKS = ["old", "older"]
    assert candidate_passphrases() == [
        derive_passphrase("new"),
        derive_passphrase("old"),
        derive_passphrase("older"),
    ]


def test_explicit_options_win_over_the_derived_key(monkeypatch):
    monkeypatch.delenv("DBS_PASSPHRASE", raising=False)
    assert resolve_passphrase("given") == "given"
    assert passphrase_source("given") == "the --passphrase option"

    monkeypatch.setenv("DBS_PASSPHRASE", "from-env")
    assert resolve_passphrase(None) == "from-env"
    assert passphrase_source(None) == "$DBS_PASSPHRASE"

    monkeypatch.delenv("DBS_PASSPHRASE")
    assert resolve_passphrase(None) == default_passphrase()
    assert passphrase_source(None) == "SECRET_KEY"


def test_the_settings_passphrase_is_read_when_the_environment_is_empty(
    monkeypatch, settings
):
    monkeypatch.delenv("DBS_PASSPHRASE", raising=False)
    settings.DBS_PASSPHRASE = "from-settings"
    assert resolve_passphrase(None) == "from-settings"


def test_a_read_needs_no_passphrase_when_one_can_be_derived(monkeypatch):
    monkeypatch.delenv("DBS_PASSPHRASE", raising=False)
    assert resolve_read_passphrase(None) is None


def test_with_passphrase_tries_the_fallbacks(settings):
    settings.SECRET_KEY = "original"
    settings.SECRET_KEY_FALLBACKS = []
    secret = default_passphrase()

    settings.SECRET_KEY = "rotated"
    settings.SECRET_KEY_FALLBACKS = ["original"]

    seen = []

    def action(candidate):
        seen.append(candidate)
        if candidate != secret:
            raise InvalidPassphrase("nope")
        return "unlocked"

    assert with_passphrase(action) == "unlocked"
    assert len(seen) == 2


def test_with_passphrase_reraises_when_nothing_fits(settings):
    settings.SECRET_KEY_FALLBACKS = []

    def action(candidate):
        raise InvalidPassphrase("nope")

    with pytest.raises(InvalidPassphrase):
        with_passphrase(action)


@pytest.mark.django_db
def test_a_backup_taken_under_secret_key_restores_after_a_rotation(settings, monkeypatch):
    monkeypatch.delenv("DBS_PASSPHRASE", raising=False)
    settings.SECRET_KEY = "before-rotation"
    settings.SECRET_KEY_FALLBACKS = []
    Author.objects.create(name="Ada")
    container = create_backup(default_passphrase())

    Author.objects.all().delete()
    settings.SECRET_KEY = "after-rotation"
    settings.SECRET_KEY_FALLBACKS = ["before-rotation"]

    result = with_passphrase(lambda secret: restore_backup(container, secret))
    assert result.records_loaded == 1
    assert Author.objects.get().name == "Ada"


@pytest.mark.django_db
def test_a_rotation_without_a_fallback_cannot_open_the_backup(settings, monkeypatch):
    monkeypatch.delenv("DBS_PASSPHRASE", raising=False)
    settings.SECRET_KEY = "before-rotation"
    settings.SECRET_KEY_FALLBACKS = []
    container = create_backup(default_passphrase())

    settings.SECRET_KEY = "after-rotation"
    with pytest.raises(InvalidPassphrase):
        with_passphrase(lambda secret: restore_backup(container, secret))


@pytest.mark.django_db
def test_backup_and_restore_commands_need_no_passphrase(tmp_path, monkeypatch):
    monkeypatch.delenv("DBS_PASSPHRASE", raising=False)
    Author.objects.create(name="Grace")
    output = tmp_path / "auto.dbs"
    out = StringIO()

    call_command("dbs", "backup", str(output), stdout=out, **FAST)
    assert "SECRET_KEY" in out.getvalue()

    Author.objects.all().delete()
    call_command("dbs", "restore", str(output), stdout=StringIO())
    assert Author.objects.get().name == "Grace"


@pytest.mark.django_db
def test_the_key_command_reports_and_shows(monkeypatch):
    monkeypatch.delenv("DBS_PASSPHRASE", raising=False)
    quiet, loud = StringIO(), StringIO()

    call_command("dbs", "key", stdout=quiet)
    assert "derived from SECRET_KEY" in quiet.getvalue()
    assert default_passphrase() not in quiet.getvalue()

    call_command("dbs", "key", "--show", stdout=loud, stderr=StringIO())
    assert default_passphrase() in loud.getvalue()


def test_no_secret_key_at_all_is_an_error(settings, monkeypatch):
    monkeypatch.delenv("DBS_PASSPHRASE", raising=False)
    settings.SECRET_KEY = ""
    settings.SECRET_KEY_FALLBACKS = []
    with pytest.raises(CommandError):
        call_command("dbs", "key", "--show", stdout=StringIO())
