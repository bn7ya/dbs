from __future__ import annotations

import re
from dataclasses import dataclass

NAME_MAX_LENGTH = 255
QUOTES = ("'", '"')

ASSIGNMENT = re.compile(
    r"[^\S\n]*(?:export[^\S\n]+)?"
    rf"([A-Za-z_][A-Za-z0-9_.-]{{0,{NAME_MAX_LENGTH - 1}}})"
    r"[^\S\n]*=[^\S\n]*"
)
INLINE_COMMENT = re.compile(r"\s+#")
AFTER_QUOTE = re.compile(r"[^\S\n]*(?:#.*)?")


@dataclass(frozen=True)
class Diff:
    added: list[str]
    removed: list[str]
    changed: list[str]


def parse(content: bytes) -> dict[str, str]:
    lines = [line.removesuffix("\r") for line in _text(content).split("\n")]
    found: dict[str, str] = {}
    number = 0
    while number < len(lines):
        line = lines[number]
        number += 1
        assignment = ASSIGNMENT.match(line)
        if assignment is None:
            continue
        if line[assignment.end() : assignment.end() + 1] in QUOTES:
            quoted = _quoted(lines, number - 1, assignment.end())
            if quoted is None:
                continue
            value, number, after = quoted
            if not AFTER_QUOTE.fullmatch(after):
                continue
        else:
            value = _unquoted(line[assignment.end() :])
        found[assignment.group(1)] = value
    return found


def key_names(content: bytes) -> list[str]:
    return list(parse(content))


def diff(old: bytes, new: bytes) -> Diff:
    before, after = parse(old), parse(new)
    return Diff(
        added=[name for name in after if name not in before],
        removed=[name for name in before if name not in after],
        changed=[
            name for name in after if name in before and before[name] != after[name]
        ],
    )


def _text(content: bytes) -> str:
    return content.decode("utf-8", errors="surrogateescape").removeprefix("﻿")


def _unquoted(rest: str) -> str:
    comment = INLINE_COMMENT.search(rest)
    return (rest if comment is None else rest[: comment.start()]).rstrip()


def _quoted(lines: list[str], first: int, column: int) -> tuple[str, int, str] | None:
    quote = lines[first][column]
    parts = []
    number, start = first, column + 1
    while number < len(lines):
        text = lines[number]
        end = _closing(text, start, quote)
        if end is not None:
            parts.append(text[start:end])
            return "\n".join(parts), number + 1, text[end + 1 :]
        parts.append(text[start:])
        number, start = number + 1, 0
    return None


def _closing(text: str, start: int, quote: str) -> int | None:
    index = start
    while index < len(text):
        if text[index] == "\\" and quote == '"':
            index += 2
        elif text[index] == quote:
            return index
        else:
            index += 1
    return None
