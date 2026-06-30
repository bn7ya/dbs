"""Shared helpers for the management commands (passphrase resolution, etc.)."""

from __future__ import annotations

import getpass
import os

from django.core.management.base import CommandError

ENV_VAR = "DBS_PASSPHRASE"


def resolve_passphrase(option_value: str | None, *, confirm: bool = False) -> str:
    """Resolve a passphrase from the CLI option, the environment, or a prompt.

    Order: explicit ``--passphrase`` > ``$DBS_PASSPHRASE`` > interactive prompt.
    When ``confirm`` is set (backups), an interactive prompt asks twice.
    """
    if option_value:
        return option_value
    env_value = os.environ.get(ENV_VAR)
    if env_value:
        return env_value
    passphrase = getpass.getpass("DBS passphrase: ")
    if not passphrase:
        raise CommandError("A passphrase is required.")
    if confirm:
        again = getpass.getpass("Confirm passphrase: ")
        if again != passphrase:
            raise CommandError("Passphrases did not match.")
    return passphrase
