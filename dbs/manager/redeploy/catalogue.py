from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from rest_framework.exceptions import ErrorDetail, ValidationError

STEPS_MAX = 12
TIMEOUT_MIN = 1
TIMEOUT_MAX = 120
TIMEOUT_DEFAULT = 10
SERVICES_MAX = 20
GIT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$")
SERVICE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
UNIT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9@._-]{0,99}\.service$")
RELATIVE_FILE = re.compile(r"^(?!-)(?!/)(?!(.*/)?\.\.(/|$))[A-Za-z0-9._/-]{1,200}$")
NO_PROMPT = {"GIT_TERMINAL_PROMPT": "0"}

GIT_PULL = "git_pull"
COMPOSE_PULL = "compose_pull"
COMPOSE_BUILD = "compose_build"
COMPOSE_UP = "compose_up"
RESTART = "restart"
SYSTEMD_USER_RESTART = "systemd_user_restart"
PIP_INSTALL = "pip_install"
MIGRATE = "migrate"
COLLECTSTATIC = "collectstatic"
KINDS = (
    GIT_PULL,
    COMPOSE_PULL,
    COMPOSE_BUILD,
    COMPOSE_UP,
    RESTART,
    SYSTEMD_USER_RESTART,
    PIP_INSTALL,
    MIGRATE,
    COLLECTSTATIC,
)
COMPOSE_KINDS = (COMPOSE_PULL, COMPOSE_BUILD, COMPOSE_UP)
MANAGE_KINDS = (MIGRATE, COLLECTSTATIC)

TOO_MANY = "An application runs at most 12 deploy steps."
UNKNOWN_KIND = "Choose one of the steps the manager offers."
NEEDS_FOLDER = "This step runs in the application's folder on the server; set it first."
NEEDS_COMPOSE = "This step runs for an application in a Compose service."
NEEDS_CONTAINER = "This step restarts the application's container or Compose service."
ON_HOST_ONLY = "This step runs for an application on the server itself."
BAD_GIT_NAME = "Use letters, digits, dots, dashes, underscores and slashes."
BAD_SERVICE = "Name Compose services with letters, digits, dots, dashes and underscores."
BAD_UNIT = "Name a user unit that ends in .service."
BAD_REQUIREMENTS = "Name a file inside the application's folder, such as requirements.txt."
BAD_TIMEOUT = "Allow 1 to 120 minutes."
UNKNOWN_OPTION = "This step takes no such option."
REMOTE_NEEDS_BRANCH = "Name the branch together with its remote."


@dataclass(frozen=True)
class Command:
    argv: list[str]
    cwd: str | None = None
    env: Mapping[str, str] | None = None
    manage: bool = False


@dataclass(frozen=True)
class Place:
    kind: str
    project_dir: str
    python: str
    compose: Callable[..., list[str]] | None
    engine: str
    container: str
    service: str


def validated(steps: Any, application: Any) -> list[dict[str, Any]]:
    if not isinstance(steps, list):
        raise ValidationError({"steps": [ErrorDetail(UNKNOWN_KIND, code="invalid")]})
    if len(steps) > STEPS_MAX:
        raise ValidationError({"steps": [ErrorDetail(TOO_MANY, code="too_many_steps")]})
    cleaned = []
    errors: dict[str, list[ErrorDetail]] = {}
    for index, step in enumerate(steps):
        problems: list[ErrorDetail] = []
        found = _step(step, application, problems)
        if problems:
            errors[f"steps.{index}"] = problems
        else:
            cleaned.append(found)
    if errors:
        raise ValidationError(errors)
    return cleaned


def run_command(step: Mapping[str, Any], place: Place) -> Command:
    kind, options = step["kind"], step.get("options") or {}
    if kind == GIT_PULL:
        named = [options[name] for name in ("remote", "branch") if options.get(name)]
        return Command(
            ["git", "-C", place.project_dir, "pull", "--ff-only", "--no-rebase", *named],
            env=NO_PROMPT,
        )
    if kind == COMPOSE_PULL:
        return _compose(place, "pull", *options.get("services", []))
    if kind == COMPOSE_BUILD:
        pull = ["--pull"] if options.get("pull") else []
        return _compose(place, "build", *pull, *options.get("services", []))
    if kind == COMPOSE_UP:
        return _compose(place, "up", "-d", *options.get("services", []))
    if kind == RESTART:
        if place.compose is not None:
            return _compose(place, "restart", place.service)
        return Command([place.engine, "restart", place.container])
    if kind == SYSTEMD_USER_RESTART:
        return Command(["systemctl", "--user", "restart", options["unit"]])
    if kind == PIP_INSTALL:
        return Command(
            [place.python, "-m", "pip", "install", "-r", options["requirements"]],
            cwd=place.project_dir,
        )
    if kind == MIGRATE:
        return Command(["migrate", "--noinput"], manage=True)
    return Command(["collectstatic", "--noinput"], manage=True)


def rehearsal_commands(step: Mapping[str, Any], place: Place) -> list[Command]:
    kind, options = step["kind"], step.get("options") or {}
    if kind == GIT_PULL:
        named = [options[name] for name in ("remote", "branch") if options.get(name)]
        return [
            Command(
                ["git", "-C", place.project_dir, "fetch", "--dry-run", *named[:1]],
                env=NO_PROMPT,
            ),
            Command(["git", "-C", place.project_dir, "status", "--porcelain"]),
        ]
    if kind in COMPOSE_KINDS:
        return [_compose(place, "config", "--quiet")]
    if kind == PIP_INSTALL:
        return [
            Command([place.python, "-m", "pip", "--version"]),
            Command(["test", "-r", options["requirements"]], cwd=place.project_dir),
        ]
    if kind == MIGRATE:
        return [Command(["migrate", "--plan"], manage=True)]
    if kind == COLLECTSTATIC:
        return [Command(["collectstatic", "--noinput", "--dry-run"], manage=True)]
    return []


def _compose(place: Place, *arguments: str) -> Command:
    if place.compose is None:
        raise ValueError("This application does not run in a Compose service.")
    return Command(place.compose(*arguments), cwd=place.project_dir or None)


def _step(step: Any, application: Any, problems: list[ErrorDetail]) -> dict[str, Any]:
    if not isinstance(step, Mapping) or step.get("kind") not in KINDS:
        problems.append(ErrorDetail(UNKNOWN_KIND, code="unknown_step"))
        return {}
    kind = step["kind"]
    options = step.get("options") or {}
    if not isinstance(options, Mapping):
        problems.append(ErrorDetail(UNKNOWN_OPTION, code="unknown_option"))
        return {}
    timeout = step.get("timeout_minutes", TIMEOUT_DEFAULT)
    if not isinstance(timeout, int) or not TIMEOUT_MIN <= timeout <= TIMEOUT_MAX:
        problems.append(ErrorDetail(BAD_TIMEOUT, code="invalid_timeout"))
    _fits(kind, application, problems)
    cleaned = _options(kind, options, problems)
    return {"kind": kind, "options": cleaned, "timeout_minutes": timeout}


def _fits(kind: str, application: Any, problems: list[ErrorDetail]) -> None:
    if kind in (GIT_PULL, PIP_INSTALL) and not application.project_dir:
        problems.append(ErrorDetail(NEEDS_FOLDER, code="project_dir_required"))
    if kind in COMPOSE_KINDS and application.kind != "compose":
        problems.append(ErrorDetail(NEEDS_COMPOSE, code="compose_required"))
    if kind == RESTART and application.kind == "host":
        problems.append(ErrorDetail(NEEDS_CONTAINER, code="container_required"))
    if kind == PIP_INSTALL and application.kind != "host":
        problems.append(ErrorDetail(ON_HOST_ONLY, code="host_required"))


def _options(
    kind: str, options: Mapping[str, Any], problems: list[ErrorDetail]
) -> dict[str, Any]:
    allowed = {
        GIT_PULL: {"remote", "branch"},
        COMPOSE_PULL: {"services"},
        COMPOSE_BUILD: {"services", "pull"},
        COMPOSE_UP: {"services"},
        SYSTEMD_USER_RESTART: {"unit"},
        PIP_INSTALL: {"requirements"},
    }.get(kind, set())
    if set(options) - allowed:
        problems.append(ErrorDetail(UNKNOWN_OPTION, code="unknown_option"))
        return {}
    cleaned: dict[str, Any] = {}
    if kind == GIT_PULL:
        for name in ("remote", "branch"):
            value = options.get(name) or ""
            if value and not (isinstance(value, str) and GIT_NAME.match(value)):
                problems.append(ErrorDetail(BAD_GIT_NAME, code="invalid_name"))
            elif value:
                cleaned[name] = value
        if "remote" in cleaned and "branch" not in cleaned:
            problems.append(ErrorDetail(REMOTE_NEEDS_BRANCH, code="branch_required"))
    if "services" in allowed:
        services = options.get("services") or []
        if (
            not isinstance(services, list)
            or len(services) > SERVICES_MAX
            or not all(isinstance(name, str) and SERVICE_NAME.match(name) for name in services)
        ):
            problems.append(ErrorDetail(BAD_SERVICE, code="invalid_service"))
        else:
            cleaned["services"] = list(dict.fromkeys(services))
    if kind == COMPOSE_BUILD:
        cleaned["pull"] = bool(options.get("pull"))
    if kind == SYSTEMD_USER_RESTART:
        unit = options.get("unit")
        if not (isinstance(unit, str) and UNIT_NAME.match(unit)):
            problems.append(ErrorDetail(BAD_UNIT, code="invalid_unit"))
        else:
            cleaned["unit"] = unit
    if kind == PIP_INSTALL:
        requirements = options.get("requirements")
        if not (isinstance(requirements, str) and RELATIVE_FILE.match(requirements)):
            problems.append(ErrorDetail(BAD_REQUIREMENTS, code="invalid_requirements"))
        else:
            cleaned["requirements"] = requirements
    return cleaned
