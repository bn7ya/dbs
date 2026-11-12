from __future__ import annotations

import colorsys
from collections.abc import Mapping
from dataclasses import dataclass, replace
from functools import lru_cache

TOKENS = {
    "ground": "#f6f8fb",
    "surface": "#ffffff",
    "on-surface": "#182030",
    "on-surface-variant": "#52607a",
    "outline": "#d8dfea",
    "primary": "#1d5bd6",
    "on-primary": "#ffffff",
    "primary-container": "#e8effd",
    "on-primary-container": "#0f3a8c",
    "danger": "#b42318",
    "on-danger": "#ffffff",
    "danger-container": "#fdecea",
    "on-danger-container": "#7a1a12",
    "success": "#17663a",
    "success-container": "#e6f4ec",
    "on-success-container": "#0f3d22",
    "warning": "#8a5300",
    "warning-container": "#fdf3e1",
    "on-warning-container": "#4a2c00",
    "info": "#1d5bd6",
    "info-container": "#e8effd",
    "on-info-container": "#0f3a8c",
    "neutral-container": "#eef2f7",
    "focus": "#1d5bd6",
}
LOGO_BLUE = "#0058a4"

TRUE = "true"
INDEXED = "indexed"
BASIC = "basic"
PLAIN = "plain"

RESET = "\x1b[0m"
CUBE = (0, 95, 135, 175, 215, 255)
HUES = ((20, 31), (75, 33), (165, 32), (195, 36), (270, 34), (330, 35), (360, 31))
VIVID = 60
DARK = 0.45


@dataclass(frozen=True)
class Style:
    fg: str = ""
    bg: str = ""
    bold: bool = False
    underline: bool = False
    strong: bool = False

    def over(self, bg: str) -> Style:
        return replace(self, bg=bg)


def token(name: str) -> str:
    return TOKENS[name]


def depth(environ: Mapping[str, str]) -> str:
    if environ.get("NO_COLOR"):
        return PLAIN
    term = environ.get("TERM", "").lower()
    colours = environ.get("COLORTERM", "").lower()
    if (
        colours in ("truecolor", "24bit")
        or "direct" in term
        or environ.get("WT_SESSION")
    ):
        return TRUE
    if "256" in term:
        return INDEXED
    return BASIC


@lru_cache(maxsize=4096)
def sequence(style: Style, colours: str) -> str:
    codes = ["0"]
    if style.bold:
        codes.append("1")
    if style.underline:
        codes.append("4")
    if colours == TRUE:
        codes += _true(style)
    elif colours == INDEXED:
        codes += _indexed(style)
    elif colours == BASIC:
        codes += _basic(style)
    elif style.strong:
        codes.append("7")
    return "\x1b[" + ";".join(codes) + "m"


def rgb(colour: str) -> tuple[int, int, int]:
    value = colour.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def mixed(under: str, over: str, share: float) -> str:
    share = min(max(share, 0.0), 1.0)
    blended = (
        round(low + (high - low) * share) for low, high in zip(rgb(under), rgb(over))
    )
    return "#" + "".join(f"{part:02x}" for part in blended)


def luminance(colour: str) -> float:
    red, green, blue = (_linear(part / 255) for part in rgb(colour))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def indexed(colour: str) -> int:
    red, green, blue = rgb(colour)
    cube = [_nearest(CUBE, part) for part in (red, green, blue)]
    cube_colour = tuple(CUBE[index] for index in cube)
    grey_step = min(max(round((sum((red, green, blue)) / 3 - 8) / 10), 0), 23)
    grey = 8 + 10 * grey_step
    if _distance((red, green, blue), (grey,) * 3) < _distance(
        (red, green, blue), cube_colour
    ):
        return 232 + grey_step
    return 16 + 36 * cube[0] + 6 * cube[1] + cube[2]


def _true(style: Style) -> list[str]:
    codes = []
    if style.fg:
        codes.append("38;2;" + ";".join(str(part) for part in rgb(style.fg)))
    if style.bg:
        codes.append("48;2;" + ";".join(str(part) for part in rgb(style.bg)))
    return codes


def _indexed(style: Style) -> list[str]:
    codes = []
    if style.fg:
        codes.append(f"38;5;{indexed(style.fg)}")
    if style.bg:
        codes.append(f"48;5;{indexed(style.bg)}")
    return codes


def _basic(style: Style) -> list[str]:
    filled = bool(style.bg) and luminance(style.bg) < DARK
    codes = []
    if style.strong or filled:
        codes.append("7")
    accent = style.bg if filled else style.fg
    if accent and _chroma(accent) >= VIVID:
        codes.append(str(_basic_code(accent)))
    return codes


def _basic_code(colour: str) -> int:
    red, green, blue = (part / 255 for part in rgb(colour))
    hue = colorsys.rgb_to_hsv(red, green, blue)[0] * 360
    return next(code for limit, code in HUES if hue < limit)


def _chroma(colour: str) -> int:
    parts = rgb(colour)
    return max(parts) - min(parts)


def _nearest(levels: tuple[int, ...], value: int) -> int:
    return min(range(len(levels)), key=lambda index: abs(levels[index] - value))


def _distance(first, second) -> float:
    return sum((one - other) ** 2 for one, other in zip(first, second))


def _linear(part: float) -> float:
    return part / 12.92 if part <= 0.03928 else ((part + 0.055) / 1.055) ** 2.4
