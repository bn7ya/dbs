from __future__ import annotations

import importlib
from typing import Any

from django.conf import settings
from rest_framework.exceptions import APIException

from dbs.manager.terminal import CommandFailed
from dbs.manager.terminal.output import problem
from dbs.manager.terminal.session import TerminalSession


def dispatch(args: Any) -> int:
    settings.DBS_MANAGER_JOBS_INLINE = True
    module, name = args.handler.split(":")
    handler = getattr(importlib.import_module(f"dbs.manager.terminal.{module}"), name)
    try:
        return handler(TerminalSession(args)) or 0
    except APIException as exc:
        raise CommandFailed(problem(exc)) from exc
