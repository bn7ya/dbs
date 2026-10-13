from __future__ import annotations

import importlib
import importlib.util

DISTRIBUTION = "django-dbs"

EXTRAS = {
    "guard": ("sklearn",),
    "manager": ("rest_framework", "waitress", "paramiko"),
    "ssh": ("paramiko",),
}


def importable(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def missing(extra: str) -> list:
    return [module for module in EXTRAS[extra] if not importable(module)]


def available(extra: str) -> bool:
    return not missing(extra)


def import_error(extra: str) -> str | None:
    for module in EXTRAS[extra]:
        try:
            importlib.import_module(module)
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}"
    return None


def installed() -> list:
    return [extra for extra in EXTRAS if available(extra)]


def requirement(extras=(), version: str | None = None) -> str:
    named = f"{DISTRIBUTION}[{','.join(extras)}]" if extras else DISTRIBUTION
    return f"{named}=={version}" if version else named


def install_command(extra: str) -> str:
    return f'pip install "{requirement([extra])}"'


def manager_missing_message(modules) -> str:
    return (
        f"the DBS manager needs {', '.join(modules)}, which this environment lacks; "
        f"install them with {install_command('manager')}"
    )
