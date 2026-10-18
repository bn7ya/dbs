from __future__ import annotations

import argparse
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from typing import IO, Any, NoReturn

from dbs.manager.console.exceptions import ConsoleStopped
from dbs.manager.terminal import parsers

PROG = "django_dbs"
DESCRIPTION = "Run DBS manager commands as your own account."
WRITTEN: ContextVar[IO[str] | None] = ContextVar("dbs_console_written", default=None)


class ConsoleParser(argparse.ArgumentParser):
    def exit(self, status: int = 0, message: str | None = None) -> NoReturn:
        raise ConsoleStopped(status, message or "")

    def error(self, message: str) -> NoReturn:
        raise ConsoleStopped(2, f"{self.format_usage()}{self.prog}: error: {message}\n")

    def _print_message(self, message: str, file: IO[str] | None = None) -> None:
        written = WRITTEN.get()
        if message and written is not None:
            written.write(message)


@lru_cache(maxsize=1)
def console_parser() -> ConsoleParser:
    parser = ConsoleParser(prog=PROG, description=DESCRIPTION)
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
    parsers.register(commands, parsers.CONSOLE)
    return parser


@contextmanager
def writing_to(stream: IO[str]) -> Iterator[None]:
    token = WRITTEN.set(stream)
    try:
        yield
    finally:
        WRITTEN.reset(token)


def parsed(words: Sequence[str], stream: IO[str]) -> Any:
    parser = console_parser()
    with writing_to(stream):
        if not words:
            parser.print_help()
            raise ConsoleStopped(0)
        args = parser.parse_args(list(words))
        if getattr(args, "handler", None) is None:
            parser.print_help()
            raise ConsoleStopped(2)
    return args
