from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from dbs.manager.applications.models import Application
from dbs.manager.redeploy.catalogue import (
    GIT_PULL,
    KINDS,
    Command,
    Place,
    rehearsal_commands,
    run_command,
)
from dbs.manager.servers.exceptions import RemoteCommandFailed
from dbs.manager.servers.gateways import DbsProfile, RemoteHost
from dbs.manager.servers.services.connection_service import container_of

DEPLOY = "redeploy.deploy"
OPENING_STEPS = ("check", "safety_backup", "record_env")
CLOSING_STEP = "final_check"
SKIPPED_IN_REHEARSAL = ("record_env", CLOSING_STEP)
CHANGING_STEPS = (*KINDS, CLOSING_STEP)
FINAL_CHECKS = (("check",), ("migrate", "--check", "--noinput"))
REVISION_TIMEOUT = 30
OUTPUT_TAIL = 500
IMAGE_FORMAT = "{{.Image}}"
REVISION = re.compile(r"^(sha256:)?[0-9a-f]{7,64}$")

Detail = dict[str, Any]


def planned(steps: Sequence[Mapping[str, Any]], rehearsal: bool) -> list[Detail]:
    names: list[Detail] = [{"step": name} for name in OPENING_STEPS]
    names += [{"step": step["kind"], "index": index} for index, step in enumerate(steps)]
    names.append({"step": CLOSING_STEP})
    skipped = SKIPPED_IN_REHEARSAL if rehearsal else ()
    return [
        {**entry, "status": "skipped" if entry["step"] in skipped else "pending"}
        for entry in names
    ]


def place_of(application: Application) -> Place:
    target = container_of(application)
    return Place(
        kind=application.kind,
        project_dir=application.project_dir,
        python=application.python_path,
        compose=target.argv if target is not None and target.in_compose else None,
        engine="" if target is None else target.engine,
        container="" if target is None else target.container,
        service="" if target is None else target.service,
    )


def run_step(
    remote: RemoteHost,
    profile: DbsProfile,
    step: Mapping[str, Any],
    place: Place,
    *,
    rehearsal: bool,
) -> Detail | None:
    commands = rehearsal_commands(step, place) if rehearsal else [run_command(step, place)]
    if not commands:
        return None
    seconds = step["timeout_minutes"] * 60
    for command in commands:
        ran(remote, profile, command, seconds)
    return {"commands": len(commands)}


def ran(
    remote: RemoteHost, profile: DbsProfile, command: Command, seconds: float
) -> Any:
    if command.manage:
        result = remote.run_manage(profile, command.argv, timeout=seconds)
    else:
        result = remote.run(
            command.argv, cwd=command.cwd, env=command.env, timeout=seconds
        )
    if not result.ok:
        raise RemoteCommandFailed(
            output=f"{result.stdout}\n{result.stderr}".strip()[-OUTPUT_TAIL:]
        )
    return result


def final_checks(remote: RemoteHost, profile: DbsProfile, seconds: float) -> None:
    for arguments in FINAL_CHECKS:
        ran(remote, profile, Command(list(arguments), manage=True), seconds)


def revisions(
    remote: RemoteHost, application: Application, steps: Sequence[Mapping[str, Any]]
) -> Detail:
    found: Detail = {}
    if application.project_dir and any(step["kind"] == GIT_PULL for step in steps):
        head = _revision(
            remote, ["git", "-C", application.project_dir, "rev-parse", "HEAD"]
        )
        if head:
            found["git_head"] = head
    target = container_of(application)
    if target is not None:
        if target.in_compose:
            argv = target.argv("images", "--quiet", target.service)
        else:
            argv = [target.engine, "inspect", "--format", IMAGE_FORMAT, target.container]
        image = _revision(remote, argv, cwd=application.project_dir or None)
        if image:
            found["image"] = image
    return found


def _revision(
    remote: RemoteHost, argv: Sequence[str], cwd: str | None = None
) -> str:
    try:
        result = remote.run(argv, cwd=cwd, timeout=REVISION_TIMEOUT)
    except RemoteCommandFailed:
        return ""
    lines = (result.stdout or "").strip().splitlines()
    if not result.ok or not lines or not REVISION.match(lines[0].strip()):
        return ""
    return lines[0].strip()
