import io
from collections import deque

import pytest

from dbs.manager.menu.kit import terminal
from dbs.manager.menu.kit.keys import Key
from dbs.manager.menu.kit.terminal import (
    ECHO_INPUT,
    LINE_INPUT,
    PROCESSED_INPUT,
    VIRTUAL_INPUT,
    VIRTUAL_OUTPUT,
    WINDOWS_INPUT,
    WINDOWS_OUTPUT,
    TerminalUnavailable,
    WindowsTerminal,
)

COOKED = LINE_INPUT | ECHO_INPUT | PROCESSED_INPUT
PLAIN_OUTPUT = 0x0003


class Console:
    def __init__(self, refuses=()):
        self.modes = {WINDOWS_INPUT: COOKED, WINDOWS_OUTPUT: PLAIN_OUTPUT}
        self.refuses = set(refuses)
        self.typed = deque()

    def mode(self, handle):
        return self.modes[handle]

    def set_mode(self, handle, mode):
        if handle in self.refuses:
            return False
        self.modes[handle] = mode
        return True

    def waiting(self):
        return bool(self.typed)

    def char(self):
        return self.typed.popleft()


class Stream(io.StringIO):
    encoding = "utf-8"


@pytest.fixture
def console():
    return Console()


@pytest.fixture
def windows(console):
    return WindowsTerminal(Stream(), console)


def test_taking_the_screen_asks_for_keys_as_sequences_and_no_echo(windows, console):
    windows.enter()

    keys = console.modes[WINDOWS_INPUT]
    assert keys & VIRTUAL_INPUT and not keys & (
        LINE_INPUT | ECHO_INPUT | PROCESSED_INPUT
    )
    assert console.modes[WINDOWS_OUTPUT] & VIRTUAL_OUTPUT
    assert windows.stream.getvalue().startswith("\x1b[?1049h")


def test_giving_the_screen_back_restores_the_console_as_it_was(windows, console):
    windows.enter()

    windows.leave()

    assert console.modes == {WINDOWS_INPUT: COOKED, WINDOWS_OUTPUT: PLAIN_OUTPUT}
    assert windows.stream.getvalue().endswith("\x1b[?1049l")


def test_giving_the_screen_back_twice_does_it_once(windows):
    windows.enter()
    windows.leave()
    written = windows.stream.getvalue()

    windows.leave()

    assert windows.stream.getvalue() == written


def test_a_console_that_refuses_escape_sequences_is_left_as_it_was():
    console = Console(refuses={WINDOWS_OUTPUT})
    windows = WindowsTerminal(Stream(), console)

    with pytest.raises(TerminalUnavailable):
        windows.enter()

    assert console.modes == {WINDOWS_INPUT: COOKED, WINDOWS_OUTPUT: PLAIN_OUTPUT}
    assert windows.stream.getvalue() == ""


def test_typed_characters_become_keys(windows, console):
    windows.enter()
    console.typed.extend("a\x1b[B\r")

    assert windows.read(0) == [Key("char", "a"), Key("down"), Key("enter")]


def test_nothing_typed_is_no_key(windows):
    windows.enter()

    assert windows.read(0) == []


def test_a_lone_escape_is_the_escape_key(windows, console):
    windows.enter()
    console.typed.append("\x1b")

    assert windows.read(0) == [Key("escape")]


def test_while_a_command_runs_control_c_is_a_signal_again(windows, console):
    windows.enter()

    with windows.interruptible():
        assert console.modes[WINDOWS_INPUT] & PROCESSED_INPUT
        with windows.asking():
            assert not console.modes[WINDOWS_INPUT] & PROCESSED_INPUT
        assert console.modes[WINDOWS_INPUT] & PROCESSED_INPUT

    assert not console.modes[WINDOWS_INPUT] & PROCESSED_INPUT


def test_leaving_the_screen_for_a_while_restores_and_takes_it_again(windows, console):
    windows.enter()

    with windows.suspended():
        assert console.modes[WINDOWS_INPUT] == COOKED

    assert console.modes[WINDOWS_INPUT] & VIRTUAL_INPUT
    assert windows.stream.getvalue().count("\x1b[?1049h") == 2


def test_text_the_console_cannot_encode_is_replaced_not_refused(console):
    class Latin(io.StringIO):
        encoding = "latin-1"

    windows = WindowsTerminal(Latin(), console)

    windows.write("│ ok")

    assert windows.stream.getvalue() == "? ok" and not windows.unicode


def test_on_windows_the_console_terminal_is_the_one_opened(monkeypatch):
    monkeypatch.setattr(terminal.os, "name", "nt")
    monkeypatch.setattr(terminal, "WindowsConsole", Console)

    assert isinstance(terminal.opened(io.StringIO(), Stream()), WindowsTerminal)


def test_a_console_is_asked_whether_it_takes_escape_sequences_and_left_as_it_was(
    monkeypatch,
):
    held = Console()
    monkeypatch.setattr(terminal.os, "name", "nt")
    monkeypatch.setattr(terminal, "WindowsConsole", lambda: held)

    assert terminal.capable() is True
    assert held.modes[WINDOWS_OUTPUT] == PLAIN_OUTPUT


def test_a_console_that_refuses_or_is_no_console_cannot_show_the_menu(monkeypatch):
    def no_console():
        raise OSError("not a console")

    monkeypatch.setattr(terminal.os, "name", "nt")
    monkeypatch.setattr(
        terminal, "WindowsConsole", lambda: Console(refuses={WINDOWS_OUTPUT})
    )
    assert terminal.capable() is False

    monkeypatch.setattr(terminal, "WindowsConsole", no_console)
    assert terminal.capable() is False
