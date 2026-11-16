from __future__ import annotations

import re
from typing import Any

from rest_framework.exceptions import ErrorDetail, ValidationError

from dbs.manager.redeploy import catalogue
from dbs.manager.redeploy.catalogue import Command, Place
from dbs.manager.servers import versions

UPDATE = "application.dbs_update"
STEPS = ("check", "safety_backup", "install", "upgrade", "restart", "final_check")
REHEARSAL_STEPS = ("check", "safety_backup", "install")
CHANGING_STEPS = ("install", "upgrade", "restart", "final_check")
RESTART_KINDS = (catalogue.SYSTEMD_USER_RESTART, catalogue.RESTART)
DISTRIBUTION = "django-dbs"
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
INSTALL_SECONDS = 900.0
UPGRADE_SECONDS = 900.0
BAD_VERSION = "Name a django-dbs release as three numbers, such as 0.9.0."


def target_version(to: str) -> str:
    wanted = (to or "").strip() or versions.local_version()
    if not VERSION.match(wanted):
        raise ValidationError({"to": [ErrorDetail(BAD_VERSION, code="invalid_version")]})
    return wanted


def install_command(place: Place, installed: str | None, wanted: str) -> Command:
    if versions.at_least(installed, versions.SELF_UPDATE_FROM):
        return Command(["dbs", "upgrade", "--self", "--to", wanted, "--yes"], manage=True)
    return Command(
        [place.python, "-m", "pip", "install", "--no-input", f"{DISTRIBUTION}=={wanted}"],
        cwd=place.project_dir,
    )


def rehearsal_command(place: Place) -> Command:
    return Command([place.python, "-m", "pip", "--version"], cwd=place.project_dir)


def upgrade_command() -> Command:
    return Command(["dbs", "upgrade"], manage=True)


def restart_steps(application: Any) -> list[dict[str, Any]]:
    return [step for step in application.deploy_steps or [] if step["kind"] in RESTART_KINDS]
