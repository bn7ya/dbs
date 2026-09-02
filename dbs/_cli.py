from __future__ import annotations

import getpass
import os
import sys

from django.core.management.base import CommandError

from dbs.conf import setting
from dbs.keys import ENV_VAR, default_passphrase, has_default_passphrase


def configured_passphrase() -> str | None:
    env_value = os.environ.get(ENV_VAR)
    if env_value:
        return env_value
    from_settings = setting(ENV_VAR, None)
    if from_settings:
        return str(from_settings)
    return None


def passphrase_source(option_value: str | None, *, from_stdin: bool = False) -> str:
    if from_stdin:
        return "standard input"
    if option_value:
        return "the --passphrase option"
    if configured_passphrase():
        return f"${ENV_VAR}"
    if has_default_passphrase():
        return "SECRET_KEY"
    return "the prompt"


def resolve_passphrase(
    option_value: str | None,
    *,
    confirm: bool = False,
    from_stdin: bool = False,
) -> str:
    if from_stdin:
        return _read_passphrase_line()
    if option_value:
        return option_value
    configured = configured_passphrase()
    if configured:
        return configured
    if has_default_passphrase():
        return default_passphrase()
    passphrase = getpass.getpass("DBS passphrase: ")
    if not passphrase:
        raise CommandError("A passphrase is required.")
    if confirm:
        again = getpass.getpass("Confirm passphrase: ")
        if again != passphrase:
            raise CommandError("Passphrases did not match.")
    return passphrase


def resolve_read_passphrase(
    option_value: str | None, *, from_stdin: bool = False
) -> str | None:
    if from_stdin:
        return _read_passphrase_line()
    if option_value:
        return option_value
    configured = configured_passphrase()
    if configured:
        return configured
    if has_default_passphrase():
        return None
    passphrase = getpass.getpass("DBS passphrase: ")
    if not passphrase:
        raise CommandError("A passphrase is required.")
    return passphrase


def require_env_passphrase(command: str) -> str:
    configured = configured_passphrase()
    if configured:
        return configured
    if has_default_passphrase():
        return default_passphrase()
    raise CommandError(
        f"{command} runs unattended and has no passphrase: set SECRET_KEY so DBS "
        f"can derive one, or export ${ENV_VAR}."
    )


def _read_passphrase_line() -> str:
    line = sys.stdin.readline()
    if not line:
        raise CommandError("No passphrase arrived on standard input.")
    passphrase = line.rstrip("\r\n")
    if not passphrase:
        raise CommandError("The passphrase read from standard input was empty.")
    return passphrase
