from __future__ import annotations

import signal
import subprocess
import sys
from collections.abc import Mapping, Sequence
from typing import Any

from . import commands
from .commands import Verb
from .results import Outcome
from .session import Transcript


def run(app: Any, verb: Verb, values: Mapping[str, Any]) -> Outcome:
    with app.plain():
        print(commands.shown(app.program, verb, values), flush=True)
        code = child(commands.words(verb, values))
        app.pause()
    return Outcome(code, Transcript())


def child(words: Sequence[str]) -> int:
    previous = signal.signal(signal.SIGINT, _left_to_the_child)
    try:
        return subprocess.call([sys.executable, "-m", "dbs.manager", *words])
    finally:
        signal.signal(signal.SIGINT, previous)


def _left_to_the_child(number: int, frame: Any) -> None:
    return None
