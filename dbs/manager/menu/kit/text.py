from __future__ import annotations

import unicodedata
from collections.abc import Iterator

ELLIPSIS = "…"
ZERO_WIDTH = ("Mn", "Me", "Cf")
WIDE = ("W", "F")
CONTROL_PICTURES = 0x2400
DELETE = "\x7f"
DELETE_PICTURE = "␡"
UNKNOWN = "�"


def safe(text: object) -> str:
    return "".join(_shown(char) for char in str(text))


def _shown(char: str) -> str:
    code = ord(char)
    if code < 32:
        return chr(CONTROL_PICTURES + code)
    if char == DELETE:
        return DELETE_PICTURE
    if 0x80 <= code <= 0x9F:
        return UNKNOWN
    return char


def char_width(char: str) -> int:
    if unicodedata.category(char) in ZERO_WIDTH:
        return 0
    return 2 if unicodedata.east_asian_width(char) in WIDE else 1


def width(text: str) -> int:
    return sum(char_width(char) for char in text)


def cells(text: str) -> Iterator[tuple[str, int]]:
    cluster = ""
    size = 0
    for char in text:
        wide = char_width(char)
        if wide == 0 and cluster:
            cluster += char
            continue
        if cluster:
            yield cluster, size
        cluster, size = char, max(wide, 1) if wide else 1
    if cluster:
        yield cluster, size


def clip(text: str, columns: int, ellipsis: str = ELLIPSIS) -> str:
    if columns <= 0:
        return ""
    if width(text) <= columns:
        return text
    room = columns - width(ellipsis)
    if room < 0:
        return ""
    kept = ""
    used = 0
    for cluster, size in cells(text):
        if used + size > room:
            break
        kept += cluster
        used += size
    return kept + ellipsis


def tail(text: str, columns: int, ellipsis: str = ELLIPSIS) -> str:
    if columns <= 0:
        return ""
    if width(text) <= columns:
        return text
    room = columns - width(ellipsis)
    if room < 0:
        return ""
    kept: list[str] = []
    used = 0
    for cluster, size in reversed(list(cells(text))):
        if used + size > room:
            break
        kept.append(cluster)
        used += size
    return ellipsis + "".join(reversed(kept))


def fit(text: str, columns: int, align: str = "left", ellipsis: str = ELLIPSIS) -> str:
    clipped = clip(text, columns, ellipsis)
    room = columns - width(clipped)
    if align == "right":
        return " " * room + clipped
    if align == "center":
        return " " * (room // 2) + clipped + " " * (room - room // 2)
    return clipped + " " * room


def wrap(text: str, columns: int) -> list[str]:
    if columns <= 0:
        return []
    lines: list[str] = []
    for paragraph in text.split("\n"):
        lines.extend(_wrapped(paragraph, columns))
    return lines


def _wrapped(paragraph: str, columns: int) -> list[str]:
    if not paragraph:
        return [""]
    lines: list[str] = []
    line = ""
    for word in paragraph.split(" "):
        candidate = f"{line} {word}" if line else word
        if width(candidate) <= columns:
            line = candidate
            continue
        if line:
            lines.append(line)
        while width(word) > columns:
            head = _head(word, columns)
            lines.append(head)
            word = word[len(head) :]
        line = word
    lines.append(line)
    return lines


def _head(word: str, columns: int) -> str:
    kept = ""
    used = 0
    for cluster, size in cells(word):
        if used + size > columns:
            break
        kept += cluster
        used += size
    return kept or word[:1]
