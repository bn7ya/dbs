from __future__ import annotations

from dataclasses import dataclass

from .palette import LOGO_BLUE, Style, token

SURFACE = token("surface")
GROUND = token("ground")
TEXT = token("on-surface")

NEUTRAL = "neutral"
INFO = "info"
SUCCESS = "success"
WARNING = "warning"
DANGER = "danger"


@dataclass(frozen=True)
class Glyphs:
    horizontal: str
    vertical: str
    top_left: str
    top_right: str
    bottom_left: str
    bottom_right: str
    tee_down: str
    tee_up: str
    pointer: str
    dot: str
    ring: str
    check: str
    cross: str
    alert: str
    ellipsis: str
    right: str
    middle: str
    on: str
    off: str
    more_up: str
    more_down: str


UNICODE = Glyphs(
    horizontal="─",
    vertical="│",
    top_left="┌",
    top_right="┐",
    bottom_left="└",
    bottom_right="┘",
    tee_down="┬",
    tee_up="┴",
    pointer="▸",
    dot="●",
    ring="○",
    check="✓",
    cross="✗",
    alert="!",
    ellipsis="…",
    right="→",
    middle="·",
    on="[x]",
    off="[ ]",
    more_up="▲",
    more_down="▼",
)
ASCII = Glyphs(
    horizontal="-",
    vertical="|",
    top_left="+",
    top_right="+",
    bottom_left="+",
    bottom_right="+",
    tee_down="+",
    tee_up="+",
    pointer=">",
    dot="*",
    ring="o",
    check="+",
    cross="x",
    alert="!",
    ellipsis="...",
    right=">",
    middle="-",
    on="[x]",
    off="[ ]",
    more_up="^",
    more_down="v",
)

BASE = Style(fg=TEXT, bg=SURFACE)
PAGE = Style(fg=TEXT, bg=GROUND)
MUTED = Style(fg=token("on-surface-variant"), bg=SURFACE)
PAGE_MUTED = Style(fg=token("on-surface-variant"), bg=GROUND)
LINE = Style(fg=token("outline"), bg=SURFACE)
HEADING = Style(fg=TEXT, bg=SURFACE, bold=True)
COLUMN = Style(fg=token("on-surface-variant"), bg=SURFACE, bold=True)
ACCENT = Style(fg=token("primary"), bg=SURFACE)
BRAND = Style(fg=LOGO_BLUE, bg=SURFACE, bold=True)
CURSOR = Style(fg=token("on-primary"), bg=token("primary"), strong=True)
CHOSEN = Style(
    fg=token("on-primary-container"), bg=token("primary-container"), bold=True
)
BUTTON = Style(fg=token("on-primary"), bg=token("primary"), bold=True, strong=True)
BUTTON_IDLE = Style(fg=token("primary"), bg=token("primary-container"), bold=True)
DANGER_BUTTON = Style(fg=token("on-danger"), bg=token("danger"), bold=True, strong=True)
DANGER_IDLE = Style(fg=token("danger"), bg=token("danger-container"), bold=True)
FIELD = Style(fg=TEXT, bg=token("neutral-container"))
FIELD_ACTIVE = Style(fg=TEXT, bg=token("primary-container"))
CARET = Style(fg=token("on-primary"), bg=token("primary"), strong=True)
KEY = Style(fg=token("primary"), bg=GROUND, bold=True)
HINT = Style(fg=token("on-surface-variant"), bg=GROUND)

TONES = {
    NEUTRAL: Style(fg=token("on-surface-variant"), bg=SURFACE),
    INFO: Style(fg=token("info"), bg=SURFACE),
    SUCCESS: Style(fg=token("success"), bg=SURFACE),
    WARNING: Style(fg=token("warning"), bg=SURFACE),
    DANGER: Style(fg=token("danger"), bg=SURFACE),
}
NOTICES = {
    NEUTRAL: Style(fg=token("on-surface-variant"), bg=token("neutral-container")),
    INFO: Style(fg=token("on-info-container"), bg=token("info-container")),
    SUCCESS: Style(fg=token("on-success-container"), bg=token("success-container")),
    WARNING: Style(fg=token("on-warning-container"), bg=token("warning-container")),
    DANGER: Style(fg=token("on-danger-container"), bg=token("danger-container")),
}


def tone(name: str) -> Style:
    return TONES.get(name, TONES[NEUTRAL])


def notice(name: str) -> Style:
    return NOTICES.get(name, NOTICES[NEUTRAL])


def symbol(glyphs: Glyphs, name: str) -> str:
    return {
        NEUTRAL: glyphs.ring,
        INFO: glyphs.dot,
        SUCCESS: glyphs.check,
        WARNING: glyphs.alert,
        DANGER: glyphs.cross,
    }.get(name, glyphs.ring)
