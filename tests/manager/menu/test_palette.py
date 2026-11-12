import re
from pathlib import Path

import pytest

from dbs.manager.menu.kit import palette, theme
from dbs.manager.menu.kit.palette import BASIC, INDEXED, PLAIN, TRUE, Style

TOKENS_FILE = Path(__file__).resolve().parents[3] / "manager-ui/src/styles/_tokens.scss"
TOKEN = re.compile(r"--app-color-([a-z-]+):\s*(#[0-9a-f]{6});")
READABLE = 4.5
CUBE = (0, 95, 135, 175, 215, 255)


def indexed_colour(index):
    if index >= 232:
        grey = 8 + 10 * (index - 232)
        return f"#{grey:02x}{grey:02x}{grey:02x}"
    index -= 16
    return "#" + "".join(
        f"{CUBE[part]:02x}" for part in (index // 36, index // 6 % 6, index % 6)
    )


def contrast(first, second):
    lighter, darker = sorted(
        (palette.luminance(first), palette.luminance(second)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)


PAIRS = [
    theme.BASE,
    theme.MUTED,
    theme.HEADING,
    theme.ACCENT,
    theme.CURSOR,
    theme.CHOSEN,
    theme.BUTTON,
    theme.DANGER_BUTTON,
    theme.FIELD,
    theme.FIELD_ACTIVE,
    theme.PAGE,
    theme.HINT,
    theme.KEY,
    *theme.TONES.values(),
    *theme.NOTICES.values(),
]


def test_the_colours_are_the_interfaces_tokens():
    assert palette.TOKENS == dict(TOKEN.findall(TOKENS_FILE.read_text()))


@pytest.mark.parametrize(
    "environ, expected",
    [
        ({"TERM": "xterm-256color", "COLORTERM": "truecolor"}, TRUE),
        ({"TERM": "xterm-256color", "COLORTERM": "24bit"}, TRUE),
        ({"TERM": "xterm-direct"}, TRUE),
        ({"WT_SESSION": "1"}, TRUE),
        ({"TERM": "xterm-256color"}, INDEXED),
        ({"TERM": "screen-256color"}, INDEXED),
        ({"TERM": "xterm"}, BASIC),
        ({"TERM": "linux"}, BASIC),
        ({}, BASIC),
        ({"TERM": "xterm-256color", "COLORTERM": "truecolor", "NO_COLOR": "1"}, PLAIN),
    ],
)
def test_the_terminal_says_how_many_colours_it_shows(environ, expected):
    assert palette.depth(environ) == expected


def test_true_colour_sends_the_token_itself():
    assert palette.sequence(Style(fg="#1d5bd6", bg="#ffffff"), TRUE) == (
        "\x1b[0;38;2;29;91;214;48;2;255;255;255m"
    )


def test_256_colours_send_the_nearest_of_them():
    sent = palette.sequence(Style(fg="#1d5bd6", bg="#ffffff"), INDEXED)

    assert sent == "\x1b[0;38;5;26;48;5;231m"
    assert indexed_colour(26) == "#005fd7"


@pytest.mark.parametrize("style", PAIRS)
@pytest.mark.parametrize("colours", [TRUE, INDEXED])
def test_text_stays_readable_on_its_background(style, colours):
    fg, bg = style.fg, style.bg
    if colours == INDEXED:
        fg = indexed_colour(palette.indexed(fg))
        bg = indexed_colour(palette.indexed(bg))

    assert contrast(fg, bg) >= READABLE, (style, colours)


def test_16_colours_keep_the_terminals_own_background_and_name_the_accent():
    assert palette.sequence(theme.BASE, BASIC) == "\x1b[0m"
    assert palette.sequence(theme.ACCENT, BASIC) == "\x1b[0;34m"
    assert palette.sequence(theme.tone(theme.DANGER), BASIC) == "\x1b[0;31m"
    assert palette.sequence(theme.tone(theme.SUCCESS), BASIC) == "\x1b[0;32m"


def test_16_colours_show_the_selected_row_reversed():
    assert "7" in palette.sequence(theme.CURSOR, BASIC).strip("\x1b[m").split(";")


def test_no_color_sends_no_colour_and_still_marks_the_selected_row():
    assert palette.sequence(theme.ACCENT, PLAIN) == "\x1b[0m"
    assert palette.sequence(theme.HEADING, PLAIN) == "\x1b[0;1m"
    assert palette.sequence(theme.CURSOR, PLAIN) == "\x1b[0;7m"


def test_a_colour_mixes_towards_another_by_its_share():
    assert palette.mixed("#ffffff", "#000000", 0.0) == "#ffffff"
    assert palette.mixed("#ffffff", "#000000", 1.0) == "#000000"
    assert palette.mixed("#ffffff", "#000000", 0.5) == "#808080"
