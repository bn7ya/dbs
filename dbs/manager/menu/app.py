from __future__ import annotations

import contextlib
import io
import sys
import threading
from collections import deque
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Optional

from .kit import layout, palette, text, theme
from .kit.canvas import Area, Canvas, Painter
from .kit.dialogs import Dialog, Message
from .kit.keys import Key
from .kit.logo import Logo

TICK = 0.25
MIN_COLUMNS = 64
MIN_ROWS = 18
WIDE = 96
TALL = 26
SIDEBAR_WIDE = 26
SIDEBAR_NARROW = 20
LOGO_COLUMNS = 22
TRAIL = 3
NOTICE_ROWS = 3
ARROWS = {
    "↑↓": "Up/Down",
    "←→": "Left/Right",
    "←": "Left",
    "→": "Right",
    "↑": "Up",
    "↓": "Down",
}
KEYS_HELP = (
    "Arrow keys move. Enter opens or runs what is selected. Esc or Backspace goes "
    "back. Tab moves between the sections and the page. / filters a list. "
    "q or Ctrl+C leaves the menu. While a command runs, Ctrl+C stops it."
)


class Screen:
    title = ""

    def __init__(self, app: App) -> None:
        self.app = app

    def draw(self, canvas: Canvas, area: Area) -> Optional[tuple[int, int]]:
        return None

    def key(self, key: Key) -> bool:
        return False

    def hints(self) -> Sequence[tuple[str, str]]:
        return ()

    def resumed(self) -> None:
        return None


@dataclass(frozen=True)
class Section:
    label: str
    build: Callable[[Any], Screen]


class App:
    def __init__(
        self,
        terminal: Any,
        environ: Mapping[str, str],
        program: str = "django_dbs",
        version: str = "",
        logo: Optional[Logo] = None,
    ) -> None:
        self.terminal = terminal
        self.colours = palette.depth(environ)
        self.glyphs = theme.UNICODE if terminal.unicode else theme.ASCII
        self.painter = Painter(self.colours)
        self.program = program
        self.version = version
        self.logo = logo if terminal.unicode else None
        self.user: Any = None
        self.account = ""
        self.sections: list[Section] = []
        self.section = 0
        self.in_sidebar = True
        self.stack: list[Screen] = []
        self.dialogs: list[Dialog] = []
        self.pending: deque = deque()
        self.notice: Optional[tuple[str, str]] = None
        self.closed = False
        self.switch: Optional[Callable[[], None]] = None
        self.live = True
        self.running = False
        self.size = (0, 0)
        self.canvas: Optional[Canvas] = None
        self.lock = threading.RLock()
        self.captured = io.StringIO()
        self.plain_out = getattr(terminal, "stream", sys.stdout)
        self.plain_err = sys.stderr

    def loop(self) -> None:
        while not self.closed:
            self.draw()
            key = self.next_key()
            if key is not None:
                self.handle(key)

    def next_key(self) -> Optional[Key]:
        if not self.pending:
            self.pending.extend(self.terminal.read(TICK))
        return self.pending.popleft() if self.pending else None

    @contextlib.contextmanager
    def capturing(self) -> Iterator[None]:
        with (
            contextlib.redirect_stdout(self.captured),
            contextlib.redirect_stderr(self.captured),
        ):
            yield

    @contextlib.contextmanager
    def plain(self) -> Iterator[None]:
        with self.lock, self.terminal.suspended():
            with (
                contextlib.redirect_stdout(self.plain_out),
                contextlib.redirect_stderr(self.plain_err),
            ):
                yield
        self.painter.forget()

    def written(self) -> str:
        found = self.captured.getvalue()
        self.captured.seek(0)
        self.captured.truncate(0)
        return found

    def use(self, sections: Sequence[Section]) -> None:
        self.sections = list(sections)
        self.open(0)
        self.in_sidebar = True

    def open(self, index: int) -> None:
        self.section = index
        try:
            self.stack = [self.sections[index].build(self)]
        except Exception as exc:
            self.stack = [Screen(self)]
            self.say(f"{type(exc).__name__}: {exc}", theme.DANGER)

    def push(self, screen: Screen) -> None:
        self.stack.append(screen)
        self.in_sidebar = False

    def pop(self) -> None:
        if len(self.stack) > 1:
            self.stack.pop()
            self.stack[-1].resumed()
        else:
            self.in_sidebar = True

    def replace(self, screen: Screen) -> None:
        self.stack[-1] = screen

    @property
    def top(self) -> Screen:
        return self.stack[-1]

    def say(self, message: str, tone: str = theme.NEUTRAL) -> None:
        self.notice = (tone, message)

    def busy(self, message: str) -> None:
        kept = self.notice
        self.notice = (theme.INFO, message)
        self.draw()
        self.notice = kept

    def modal(self, dialog: Dialog) -> Any:
        self.dialogs.append(dialog)
        try:
            with self.terminal.asking():
                while not dialog.done:
                    self.draw()
                    key = self.next_key()
                    if key is not None:
                        dialog.key(key)
        finally:
            self.dialogs.pop()
        return dialog.result

    def tell(self, title: str, message: str, tone: str = theme.NEUTRAL) -> None:
        self.modal(Message(title, message, tone))

    def pause(self) -> None:
        self.terminal.pause("\nPress Enter to return to the menu. ")

    def handle(self, key: Key) -> None:
        self.notice = None
        if key.ctrl and key.text == "c":
            self.closed = True
        elif key.ctrl and key.text == "z":
            self.terminal.stop()
            self.painter.forget()
        elif key.ctrl and key.text == "l":
            self.painter.forget()
        elif self.in_sidebar:
            self._sidebar_key(key)
        else:
            self._content_key(key)

    def _sidebar_key(self, key: Key) -> None:
        if key.name in ("up", "down"):
            step = -1 if key.name == "up" else 1
            self.open((self.section + step) % len(self.sections))
        elif key.name in ("enter", "right", "tab"):
            self.in_sidebar = False
        else:
            self._common_key(key)

    def _content_key(self, key: Key) -> None:
        if self.top.key(key):
            return
        if key.name in ("escape", "backspace", "left"):
            self.pop()
        elif key.name in ("tab", "backtab"):
            self.in_sidebar = True
        else:
            self._common_key(key)

    def _common_key(self, key: Key) -> None:
        if not key.is_text():
            return
        if key.text == "q":
            self.closed = True
        elif key.text == "?":
            self.tell("Keys", KEYS_HELP)

    def draw(self) -> None:
        with self.lock:
            size = self.terminal.size()
            if size != self.size:
                self.painter.forget()
                self.size = size
            canvas = Canvas(size[0], size[1], theme.PAGE, self.glyphs.ellipsis)
            cursor = self.compose(canvas)
            self.canvas = canvas
            self.terminal.write(self.painter.paint(canvas, cursor))

    def compose(self, canvas: Canvas) -> Optional[tuple[int, int]]:
        area = canvas.area
        if area.columns < MIN_COLUMNS or area.rows < MIN_ROWS:
            layout.paragraph(
                canvas,
                area.inset(1, 0, 1, 0),
                "Make this window larger to use the menu.",
                theme.PAGE,
            )
            return None
        self._header(canvas, area.row(0))
        frame = Area(0, 1, area.columns, area.rows - 2)
        inside = layout.box(canvas, frame, self.glyphs)
        side = SIDEBAR_WIDE if area.columns >= WIDE else SIDEBAR_NARROW
        layout.divider(canvas, frame, inside.x + side, self.glyphs)
        self._sidebar(canvas, Area(inside.x, inside.y, side, inside.rows))
        content = Area(
            inside.x + side + 1, inside.y, inside.columns - side - 1, inside.rows
        )
        cursor = self._content(canvas, content.inset(1, 0, 1, 0))
        pairs = self._hints()
        if self.dialogs:
            cursor = self.dialogs[-1].draw(canvas, self.glyphs, self.terminal.unicode)
            pairs = self.dialogs[-1].hints()
        layout.hints(canvas, area.row(area.rows - 1), self._spelled(pairs))
        return cursor

    def _header(self, canvas: Canvas, area: Area) -> None:
        canvas.fill(area, theme.PAGE)
        end = canvas.put(area.x + 1, area.y, "DBS", theme.BRAND.over(theme.GROUND))
        canvas.put(
            end + 1, area.y, f"manager {self.version}".rstrip(), theme.PAGE_MUTED
        )
        if self.account:
            canvas.put(
                area.right - text.width(self.account) - 1,
                area.y,
                self.account,
                theme.PAGE_MUTED,
            )

    def _sidebar(self, canvas: Canvas, area: Area) -> None:
        y = area.y
        if self.logo is not None and canvas.columns >= WIDE and canvas.rows >= TALL:
            x = area.x + (area.columns - LOGO_COLUMNS) // 2
            y += layout.logo(canvas, x, y, self.logo, LOGO_COLUMNS, self.colours) + 1
        for index, section in enumerate(self.sections):
            if y >= area.bottom:
                break
            current = index == self.section
            style = theme.BASE
            if current:
                style = theme.CURSOR if self.in_sidebar else theme.CHOSEN
                canvas.fill(Area(area.x, y, area.columns, 1), style)
                canvas.put(area.x, y, self.glyphs.pointer, style)
            canvas.put(area.x + 2, y, section.label, style, area.columns - 2)
            y += 1

    def _content(self, canvas: Canvas, area: Area) -> Optional[tuple[int, int]]:
        titles: list[str] = []
        for screen in self.stack:
            if screen.title and screen.title not in titles[-1:]:
                titles.append(screen.title)
        titles = titles[-TRAIL:]
        canvas.put(
            area.x,
            area.y,
            f" {self.glyphs.right} ".join(titles),
            theme.HEADING,
            area.columns,
        )
        body = area.inset(top=2)
        if self.notice is not None:
            tone, message = self.notice
            lines = text.wrap(text.safe(message), max(body.columns - 4, 10))[
                :NOTICE_ROWS
            ]
            block = Area(body.x, body.bottom - len(lines), body.columns, len(lines))
            canvas.fill(block, theme.notice(tone))
            canvas.put(
                block.x + 1,
                block.y,
                theme.symbol(self.glyphs, tone),
                theme.notice(tone),
            )
            for index, line in enumerate(lines):
                canvas.put(block.x + 3, block.y + index, line, theme.notice(tone))
            body = body.inset(bottom=len(lines) + 1)
        return self.top.draw(canvas, body)

    def _hints(self) -> Sequence[tuple[str, str]]:
        if self.in_sidebar:
            return (("↑↓", "Move"), ("Enter", "Open"), ("?", "Keys"), ("q", "Quit"))
        return (*self.top.hints(), ("Esc", "Back"), ("?", "Keys"))

    def _spelled(self, pairs: Sequence[tuple[str, str]]) -> Sequence[tuple[str, str]]:
        if self.terminal.unicode:
            return pairs
        return [(ARROWS.get(key, key), label) for key, label in pairs]
