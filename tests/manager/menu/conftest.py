from __future__ import annotations

import io
from collections import deque
from contextlib import contextmanager

import pytest

from dbs.manager.menu import start
from dbs.manager.menu.app import App
from dbs.manager.menu.kit.keys import Key
from tests.manager.terminal.conftest import (  # noqa: F401
    local_host,
    make_application,
    make_server,
    storage,
)
from tests.manager.terminal.test_backups import host, two_applications  # noqa: F401
from tests.manager.terminal.test_records import application, project, umask  # noqa: F401
from tests.manager.terminal.test_servers import offered, remote  # noqa: F401

TRUE_COLOUR = {"TERM": "xterm-256color", "COLORTERM": "truecolor"}
KEYS = {
    "enter",
    "escape",
    "tab",
    "backtab",
    "up",
    "down",
    "left",
    "right",
    "home",
    "end",
    "pageup",
    "pagedown",
    "backspace",
    "delete",
}


class Waiting(BaseException):
    pass


def keys_of(press):
    if isinstance(press, Key):
        return [press]
    if press == "esc":
        return [Key("escape")]
    if press == "space":
        return [Key("char", " ")]
    if press.startswith("ctrl+"):
        return [Key("char", press[5:], ctrl=True)]
    if press in KEYS:
        return [Key(press)]
    return [Key("char", char) for char in press]


class StandInTerminal:
    def __init__(self, columns=110, rows=34, unicode=True):
        self.columns = columns
        self.rows = rows
        self.unicode = unicode
        self.keys = deque()
        self.in_dialog = None
        self.stuck = False
        self.stream = io.StringIO()
        self.paused = []
        self.entered = 0
        self.left = 0

    def size(self):
        return self.columns, self.rows

    def read(self, timeout):
        if not self.keys:
            self.stuck = bool(self.in_dialog and self.in_dialog())
            raise Waiting()
        return [self.keys.popleft()]

    def write(self, text):
        self.stream.write(text)

    def enter(self):
        self.entered += 1

    def leave(self):
        self.left += 1

    def stop(self):
        return None

    def flush_input(self):
        return None

    def pause(self, message):
        self.paused.append(message)

    @contextmanager
    def interruptible(self):
        yield

    @contextmanager
    def asking(self):
        yield

    @contextmanager
    def suspended(self):
        yield


class Menu:
    def __init__(self, app, terminal):
        self.app = app
        self.terminal = terminal
        self.frames = []
        app.plain_out = io.StringIO()
        terminal.in_dialog = lambda: app.dialogs
        draw = app.draw

        def drawn():
            draw()
            self.frames.append(app.canvas.text())

        app.draw = drawn

    def queue(self, *presses):
        for press in presses:
            self.terminal.keys.extend(keys_of(press))
        return self

    def press(self, *presses):
        self.queue(*presses)
        try:
            self.app.loop()
        except Waiting:
            if self.terminal.stuck:
                raise AssertionError(
                    f"the menu was left waiting in a dialog:\n{self.frames[-1]}"
                ) from None
        self.app.draw()
        return self

    @property
    def screen(self):
        return self.app.canvas.text()

    def saw(self, text):
        return any(text in frame for frame in self.frames)

    def line_with(self, text):
        for line in self.screen.splitlines():
            if text in line:
                return line
        raise AssertionError(f"{text!r} is not on the screen:\n{self.screen}")

    @property
    def printed(self):
        return self.app.plain_out.getvalue()


@pytest.fixture
def open_menu():
    def opened(user=None, columns=110, rows=34, unicode=True, environ=None):
        terminal = StandInTerminal(columns, rows, unicode)
        app = App(terminal, environ or TRUE_COLOUR, version="0.8.2", logo=start.logo())
        app.live = False
        menu = Menu(app, terminal)
        if user is not None:
            start.act_as(app, user)
            app.draw()
        return menu

    return opened


@pytest.fixture
def menu(open_menu, admin):
    return open_menu(admin)
