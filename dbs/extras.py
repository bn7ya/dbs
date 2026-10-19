from __future__ import annotations

import importlib
import importlib.util

DISTRIBUTION = "django-dbs"

MANAGER_MODULES = ("rest_framework", "waitress", "paramiko", "keyring")

BUNDLED = ("numpy", "sklearn", *MANAGER_MODULES)

RETIRED_EXTRAS = ("guard", "manager", "ssh", "all")


def importable(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def missing(modules=BUNDLED) -> list:
    return [module for module in modules if not importable(module)]


def import_failure(module: str) -> str | None:
    try:
        importlib.import_module(module)
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


def requirement(version: str | None = None) -> str:
    return f"{DISTRIBUTION}=={version}" if version else DISTRIBUTION


def reinstall_command(version: str | None = None) -> str:
    return f'pip install --force-reinstall "{requirement(version)}"'


def incomplete_message(modules) -> str:
    return (
        f"this django-dbs installation cannot import {', '.join(modules)}; "
        f"repair it with {reinstall_command()}"
    )
