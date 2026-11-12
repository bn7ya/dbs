from __future__ import annotations

import codecs
from dataclasses import dataclass

ESCAPE = "\x1b"
PASTE_START = 200
PASTE_END = 201
PASTE_END_SEQUENCE = "\x1b[201~"

FINALS = {
    "A": "up",
    "B": "down",
    "C": "right",
    "D": "left",
    "H": "home",
    "F": "end",
    "Z": "backtab",
    "P": "f1",
    "Q": "f2",
    "R": "f3",
    "S": "f4",
}
NUMBERED = {
    1: "home",
    2: "insert",
    3: "delete",
    4: "end",
    5: "pageup",
    6: "pagedown",
    7: "home",
    8: "end",
    11: "f1",
    12: "f2",
    13: "f3",
    14: "f4",
    15: "f5",
    17: "f6",
    18: "f7",
    19: "f8",
    20: "f9",
    21: "f10",
    23: "f11",
    24: "f12",
}
CONTROLS = {
    "\r": "enter",
    "\n": "enter",
    "\t": "tab",
    "\x7f": "backspace",
    "\x08": "backspace",
}
ALT = 2
CTRL = 4


@dataclass(frozen=True)
class Key:
    name: str
    text: str = ""
    ctrl: bool = False
    alt: bool = False

    def is_text(self) -> bool:
        return self.name == "char" and not self.ctrl and not self.alt


class Decoder:
    def __init__(self) -> None:
        self.utf8 = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.held = ""
        self.pasting = False
        self.pasted = ""

    def feed(self, data: bytes) -> list[Key]:
        return self.take(self.utf8.decode(data))

    def take(self, text: str) -> list[Key]:
        fresh = not self.held and not self.pasting
        if fresh and _looks_pasted(text):
            return [Key("paste", text)]
        self.held += text
        keys: list[Key] = []
        while self.held:
            if self.pasting:
                if not self._paste(keys):
                    break
                continue
            used, key = _one(self.held)
            if used == 0:
                break
            self.held = self.held[used:]
            if key is None:
                continue
            if key.name == "paste-start":
                self.pasting = True
                continue
            keys.append(key)
        return keys

    def flush(self) -> list[Key]:
        if self.pasting or not self.held:
            return []
        held, self.held = self.held, ""
        if held == ESCAPE:
            return [Key("escape")]
        return [Key("escape")] + self.take(held[1:]) if held[0] == ESCAPE else []

    def waiting(self) -> bool:
        return bool(self.held) and not self.pasting

    def _paste(self, keys: list[Key]) -> bool:
        end = self.held.find(PASTE_END_SEQUENCE)
        if end < 0:
            keep = _partial_end(self.held)
            self.pasted += self.held[: len(self.held) - keep]
            self.held = self.held[len(self.held) - keep :]
            return False
        self.pasted += self.held[:end]
        self.held = self.held[end + len(PASTE_END_SEQUENCE) :]
        keys.append(Key("paste", self.pasted))
        self.pasted = ""
        self.pasting = False
        return True


def _looks_pasted(text: str) -> bool:
    if ESCAPE in text or len(text) < 2:
        return False
    body = text.rstrip("\r\n")
    return "\n" in body or "\r" in body


def _partial_end(text: str) -> int:
    for size in range(min(len(PASTE_END_SEQUENCE) - 1, len(text)), 0, -1):
        if PASTE_END_SEQUENCE.startswith(text[-size:]):
            return size
    return 0


def _one(text: str) -> tuple[int, Key | None]:
    first = text[0]
    if first != ESCAPE:
        return 1, _plain(first)
    if len(text) == 1:
        return 0, None
    second = text[1]
    if second == "[":
        return _csi(text)
    if second == "O":
        if len(text) < 3:
            return 0, None
        name = FINALS.get(text[2])
        return 3, Key(name) if name else None
    if second == ESCAPE:
        return 1, Key("escape")
    plain = _plain(second)
    return 2, Key(plain.name, plain.text, plain.ctrl, True)


def _plain(char: str) -> Key:
    if char in CONTROLS:
        return Key(CONTROLS[char])
    code = ord(char)
    if code == 0:
        return Key("char", " ", ctrl=True)
    if code < 32:
        return Key("char", chr(code + 96), ctrl=True)
    return Key("char", char)


def _csi(text: str) -> tuple[int, Key | None]:
    end = 2
    while end < len(text) and not ("@" <= text[end] <= "~"):
        end += 1
    if end >= len(text):
        return 0, None
    final = text[end]
    numbers = _numbers(text[2:end])
    modifier = (numbers[1] if len(numbers) > 1 else 1) - 1
    if final == "~":
        code = numbers[0] if numbers else 0
        if code == PASTE_START:
            return end + 1, Key("paste-start")
        if code == PASTE_END:
            return end + 1, None
        name = NUMBERED.get(code)
    else:
        name = FINALS.get(final)
    if name is None:
        return end + 1, None
    return end + 1, Key(name, "", bool(modifier & CTRL), bool(modifier & ALT))


def _numbers(parameters: str) -> list[int]:
    found = []
    for part in parameters.lstrip("?<>=").split(";"):
        found.append(int(part) if part.isdigit() else 1)
    return found
