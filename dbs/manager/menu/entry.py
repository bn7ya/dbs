from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, Optional

NO_TERMINAL = ("", "dumb")


def available(environ: Mapping[str, str], stdin: Any, stdout: Any) -> bool:
    try:
        if not (stdin.isatty() and stdout.isatty()):
            return False
    except (AttributeError, ValueError):
        return False
    if os.name != "nt":
        return environ.get("TERM", "") not in NO_TERMINAL
    from .kit import terminal

    return terminal.capable()


def opened(account: Optional[str] = None) -> int:
    from dbs import __version__
    from dbs.manager.adapters import AdapterError
    from dbs.manager.cli import prog

    from .app import App
    from .kit.terminal import TerminalUnavailable, opened as open_terminal
    from .start import logo, started

    app = App(
        open_terminal(), os.environ, program=prog(), version=__version__, logo=logo()
    )
    try:
        return started(app, account)
    except TerminalUnavailable:
        raise AdapterError(
            f"this terminal cannot show the menu. Use the commands: {prog()} --help"
        ) from None
