from __future__ import annotations

import getpass
import os
import sys

from django.core.management.base import CommandError

ENV_VAR = "DBS_PASSPHRASE"


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


def require_env_passphrase(command: str) -> str:
    passphrase = os.environ.get(ENV_VAR)
    if not passphrase:
        raise CommandError(
            f"{command} runs unattended and reads the passphrase from ${ENV_VAR}; "
            "set it in the service unit or container environment."
        )
    return passphrase


def _read_passphrase_line() -> str:
    line = sys.stdin.readline()
    if not line:
        raise CommandError("No passphrase arrived on standard input.")
    passphrase = line.rstrip("\r\n")
    if not passphrase:
        raise CommandError("The passphrase read from standard input was empty.")
    return passphrase
