from __future__ import annotations

import os
from importlib import import_module

from django.apps import apps
from django.core.management import find_commands

OWN_APP = "dbs"
CORE = "django.core"


def underlying_command(name: str):
    for config in apps.get_app_configs():
        if config.name == OWN_APP:
            continue
        if name in find_commands(os.path.join(config.path, "management")):
            return import_module(f"{config.name}.management.commands.{name}").Command
    return import_module(f"{CORE}.management.commands.{name}").Command
