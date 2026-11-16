from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass, field

from dbs import upgrade

RESTART_AFTER_SECONDS = 1.0
INVALID_VERSION = "invalid_version"
UNREACHABLE = "update_unreachable"
DOWNGRADE = "update_would_downgrade"
SOURCE_CHECKOUT = "update_source_checkout"
SYSTEM_PYTHON = "update_system_python"
FAILED = "update_failed"
FROM_TERMINAL = "update_from_terminal"


class Refused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Plan:
    current: str
    target: str
    command: list = field(default_factory=list)

    @property
    def needed(self) -> bool:
        return bool(self.command)


class Restart:
    def __init__(self) -> None:
        self.argv: list | None = None
        self.requested = threading.Event()

    def arm(self, arguments: list) -> None:
        self.argv = [sys.executable, "-m", "dbs.manager", *arguments]
        self.requested.clear()

    def disarm(self) -> None:
        self.argv = None
        self.requested.clear()

    @property
    def armed(self) -> bool:
        return self.argv is not None and os.name != "nt"

    def request(self, delay: float = RESTART_AFTER_SECONDS) -> bool:
        if not self.armed:
            return False
        self.requested.set()
        timer = threading.Timer(delay, os.kill, (os.getpid(), signal.SIGTERM))
        timer.daemon = True
        timer.start()
        return True

    def follow(self) -> None:
        if self.armed and self.requested.is_set():
            os.execv(self.argv[0], self.argv)


RESTART = Restart()


def run_arguments(args, port: int, data_dir) -> list:
    found = ["run", "--no-browser", "--host", args.host, "--port", str(port)]
    found += ["--data-dir", str(data_dir)]
    for proxy in args.trusted_proxy or ():
        found += ["--trusted-proxy", proxy]
    if args.allow_insecure_http:
        found.append("--allow-insecure-http")
    if args.terminal:
        found += ["--terminal", args.terminal]
    if args.database_url:
        found += ["--database-url", args.database_url]
    return found


def standing_refusal(*, system_python: bool = False) -> Refused | None:
    if upgrade.is_editable_install():
        return Refused(
            SOURCE_CHECKOUT,
            "this manager runs from a source checkout; update it with git.",
        )
    if upgrade.is_system_interpreter() and not system_python:
        return Refused(
            SYSTEM_PYTHON,
            "this manager is installed in a Python outside a virtual environment, whose "
            "packages the operating system or other programs may share. Update it with "
            "the tool that installed it, or add --system-python if this Python is yours "
            "to change.",
        )
    return None


def wanted_version(to: str, *, offline: bool) -> str:
    named = (to or "").strip()
    if named:
        if not upgrade.is_version(named):
            raise Refused(INVALID_VERSION, f"{named!r} is not a django-dbs release such as 0.9.0.")
        return named
    newest = None if offline else upgrade.latest_release()
    if newest is None or not upgrade.is_version(newest):
        raise Refused(
            UNREACHABLE,
            "could not reach PyPI to find the newest release; name one with --to VERSION.",
        )
    return newest


def plan(to: str = "", *, offline: bool = False, system_python: bool = False) -> Plan:
    current = upgrade.installed_version()
    target = wanted_version(to, offline=offline)
    if target == current:
        return Plan(current, target)
    if not upgrade.is_newer(target, current):
        raise Refused(DOWNGRADE, f"django-dbs {current} is installed, newer than {target}.")
    refusal = standing_refusal(system_python=system_python)
    if refusal is not None:
        raise refusal
    return Plan(current, target, upgrade.pinned_install_command(target))


def install(found: Plan) -> None:
    result = subprocess.run(found.command, capture_output=True, text=True)
    if result.returncode != 0:
        lines = (result.stderr or result.stdout).strip().splitlines()
        raise Refused(FAILED, "pip failed: " + (lines[-1] if lines else "no output"))


def status(*, offline: bool = False) -> dict:
    current = upgrade.installed_version()
    newest = None if offline else upgrade.latest_release()
    refusal = standing_refusal()
    code = refusal.code if refusal is not None else (None if RESTART.armed else FROM_TERMINAL)
    return {
        "current": current,
        "latest": newest,
        "newer": bool(newest and upgrade.is_version(newest) and upgrade.is_newer(newest, current)),
        "refusal": code,
    }
