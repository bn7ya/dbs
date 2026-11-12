from __future__ import annotations

import os
import shutil
import signal
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Optional

from .keys import Decoder, Key

ENTER_SCREEN = "\x1b[?1049h\x1b[?25l\x1b[?2004h\x1b[?7l"
LEAVE_SCREEN = "\x1b[0m\x1b[?7h\x1b[?2004l\x1b[?25h\x1b[?1049l"
ESCAPE_WAIT = 0.05
POLL = 0.01
FALLBACK_SIZE = (80, 24)
STOPPING = ("SIGTERM", "SIGHUP")
UTF8 = ("utf-8", "utf8")

WINDOWS_INPUT = -10
WINDOWS_OUTPUT = -11
PROCESSED_INPUT = 0x0001
LINE_INPUT = 0x0002
ECHO_INPUT = 0x0004
VIRTUAL_INPUT = 0x0200
PROCESSED_OUTPUT = 0x0001
VIRTUAL_OUTPUT = 0x0004


class TerminalUnavailable(Exception):
    pass


class Terminal:
    def __init__(self, stream: Any) -> None:
        self.stream = stream
        self.decoder = Decoder()
        self.held = False
        self.signalled = False
        self.handlers: dict[int, Any] = {}

    @property
    def unicode(self) -> bool:
        return (getattr(self.stream, "encoding", "") or "").lower() in UTF8

    def size(self) -> tuple[int, int]:
        found = shutil.get_terminal_size(FALLBACK_SIZE)
        return found.columns, found.lines

    def write(self, text: str) -> None:
        encoding = getattr(self.stream, "encoding", None) or "utf-8"
        self.stream.write(text.encode(encoding, "replace").decode(encoding))
        self.stream.flush()

    def enter(self) -> None:
        if self.held:
            return
        self._raw()
        self.held = True
        self._watch_signals()
        self.write(ENTER_SCREEN)

    def leave(self) -> None:
        if not self.held:
            return
        self.held = False
        try:
            self.write(LEAVE_SCREEN)
        finally:
            self._restore()
            self._unwatch_signals()

    def read(self, timeout: float) -> list[Key]:
        keys = self.decoder.take(self._text(timeout))
        if self.decoder.waiting():
            keys += self.decoder.take(self._text(ESCAPE_WAIT))
            keys += self.decoder.flush()
        return keys

    @contextmanager
    def interruptible(self) -> Iterator[None]:
        self._signals(True)
        self.signalled = True
        try:
            yield
        finally:
            self.signalled = False
            self._signals(False)
            self.flush_input()

    @contextmanager
    def asking(self) -> Iterator[None]:
        signalled = self.signalled
        if signalled:
            self.signalled = False
            self._signals(False)
        try:
            yield
        finally:
            if signalled:
                self._signals(True)
                self.signalled = True

    @contextmanager
    def suspended(self) -> Iterator[None]:
        self.leave()
        try:
            yield
        finally:
            self.enter()

    def stop(self) -> None:
        if not hasattr(signal, "SIGTSTP"):
            return
        with self.suspended():
            signal.raise_signal(signal.SIGTSTP)

    def flush_input(self) -> None:
        self.decoder = Decoder()

    def pause(self, message: str) -> None:
        self.write(message)
        try:
            sys.stdin.readline()
        except (EOFError, KeyboardInterrupt):
            return

    def _watch_signals(self) -> None:
        for name in STOPPING:
            number = getattr(signal, name, None)
            if number is None:
                continue
            try:
                self.handlers[number] = signal.signal(number, self._stopped)
            except ValueError:
                return

    def _unwatch_signals(self) -> None:
        while self.handlers:
            number, handler = self.handlers.popitem()
            signal.signal(number, handler)

    def _stopped(self, number: int, frame: Any) -> None:
        raise SystemExit(128 + number)

    def _raw(self) -> None:
        raise NotImplementedError

    def _restore(self) -> None:
        raise NotImplementedError

    def _signals(self, on: bool) -> None:
        raise NotImplementedError

    def _text(self, timeout: float) -> str:
        raise NotImplementedError


class PosixTerminal(Terminal):
    def __init__(self, stream: Any, descriptor: int) -> None:
        super().__init__(stream)
        self.descriptor = descriptor
        self.saved: Optional[list] = None

    def read(self, timeout: float) -> list[Key]:
        keys = self.decoder.feed(self._bytes(timeout))
        if self.decoder.waiting():
            keys += self.decoder.feed(self._bytes(ESCAPE_WAIT))
            keys += self.decoder.flush()
        return keys

    def flush_input(self) -> None:
        import termios

        super().flush_input()
        termios.tcflush(self.descriptor, termios.TCIFLUSH)

    def _raw(self) -> None:
        import termios

        self.saved = termios.tcgetattr(self.descriptor)
        self._apply(signals=False)

    def _restore(self) -> None:
        import termios

        if self.saved is not None:
            termios.tcsetattr(self.descriptor, termios.TCSADRAIN, self.saved)
            self.saved = None

    def _signals(self, on: bool) -> None:
        self._apply(signals=on)

    def _apply(self, signals: bool) -> None:
        import termios

        mode = termios.tcgetattr(self.descriptor)
        mode[0] &= ~(termios.IXON | termios.ICRNL | termios.INLCR)
        mode[3] &= ~(termios.ICANON | termios.ECHO | termios.IEXTEN | termios.ISIG)
        if signals:
            mode[3] |= termios.ISIG
            disabled = _disabled(self.descriptor)
            mode[6][termios.VSUSP] = disabled
            mode[6][termios.VQUIT] = disabled
        mode[6][termios.VMIN] = 0
        mode[6][termios.VTIME] = 0
        termios.tcsetattr(self.descriptor, termios.TCSADRAIN, mode)

    def _bytes(self, timeout: float) -> bytes:
        import select

        ready, _, _ = select.select([self.descriptor], [], [], max(timeout, 0))
        if not ready:
            return b""
        return os.read(self.descriptor, 4096)


class WindowsTerminal(Terminal):
    def __init__(self, stream: Any, console: Any) -> None:
        super().__init__(stream)
        self.console = console
        self.saved: Optional[tuple[int, int]] = None

    def _raw(self) -> None:
        self.saved = (
            self.console.mode(WINDOWS_INPUT),
            self.console.mode(WINDOWS_OUTPUT),
        )
        self._apply(signals=False)
        wanted = self.saved[1] | PROCESSED_OUTPUT | VIRTUAL_OUTPUT
        if not self.console.set_mode(WINDOWS_OUTPUT, wanted):
            self._restore()
            raise TerminalUnavailable()

    def _restore(self) -> None:
        if self.saved is not None:
            self.console.set_mode(WINDOWS_INPUT, self.saved[0])
            self.console.set_mode(WINDOWS_OUTPUT, self.saved[1])
            self.saved = None

    def _signals(self, on: bool) -> None:
        self._apply(signals=on)

    def _apply(self, signals: bool) -> None:
        mode = self.saved[0] & ~(LINE_INPUT | ECHO_INPUT | PROCESSED_INPUT)
        mode |= VIRTUAL_INPUT
        if signals:
            mode |= PROCESSED_INPUT
        if not self.console.set_mode(WINDOWS_INPUT, mode):
            self._restore()
            raise TerminalUnavailable()

    def _text(self, timeout: float) -> str:
        deadline = time.monotonic() + max(timeout, 0)
        while not self.console.waiting():
            if time.monotonic() >= deadline:
                return ""
            time.sleep(POLL)
        typed = ""
        while self.console.waiting():
            typed += self.console.char()
        return typed


class WindowsConsole:
    def __init__(self) -> None:
        import ctypes
        import msvcrt

        self.ctypes = ctypes
        self.msvcrt = msvcrt
        self.kernel = ctypes.windll.kernel32

    def mode(self, handle: int) -> int:
        current = self.ctypes.c_uint32()
        if not self.kernel.GetConsoleMode(
            self.kernel.GetStdHandle(handle), self.ctypes.byref(current)
        ):
            raise TerminalUnavailable()
        return current.value

    def set_mode(self, handle: int, mode: int) -> bool:
        return bool(self.kernel.SetConsoleMode(self.kernel.GetStdHandle(handle), mode))

    def waiting(self) -> bool:
        return bool(self.msvcrt.kbhit())

    def char(self) -> str:
        return self.msvcrt.getwch()


def _disabled(descriptor: int) -> bytes:
    try:
        return bytes([os.fpathconf(descriptor, "PC_VDISABLE")])
    except (OSError, ValueError):
        return b"\x00"


def capable() -> bool:
    if os.name != "nt":
        return True
    try:
        console = WindowsConsole()
        before = console.mode(WINDOWS_OUTPUT)
        able = console.set_mode(
            WINDOWS_OUTPUT, before | PROCESSED_OUTPUT | VIRTUAL_OUTPUT
        )
        console.set_mode(WINDOWS_OUTPUT, before)
    except Exception:
        return False
    return able


def opened(stdin: Any = None, stdout: Any = None) -> Terminal:
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    if os.name == "nt":
        return WindowsTerminal(stdout, WindowsConsole())
    return PosixTerminal(stdout, stdin.fileno())
