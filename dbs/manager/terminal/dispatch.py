from __future__ import annotations

import importlib
from typing import Any

from rest_framework.exceptions import APIException

from dbs.manager.adapters.problems import problem
from dbs.manager.conf import inline_jobs
from dbs.manager.terminal import CommandFailed
from dbs.manager.terminal.session import TerminalSession


def handler_of(args: Any) -> Any:
    module, name = args.handler.split(":")
    return getattr(importlib.import_module(f"dbs.manager.{module}"), name)


def dispatch(args: Any) -> int:
    handler = handler_of(args)
    try:
        with inline_jobs():
            return handler(TerminalSession(args)) or 0
    except APIException as exc:
        raise CommandFailed(problem(exc)) from exc
