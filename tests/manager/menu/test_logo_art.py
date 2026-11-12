from pathlib import Path

from dbs.manager.menu import start
from dbs.manager.menu.kit import layout, logo, palette, theme
from dbs.manager.menu.kit.canvas import Canvas

ROOT = Path(__file__).resolve().parents[3]
OFFICIAL = ROOT / "docs/assets/dbs-logo.svg"
SHIPPED = ROOT / "dbs/static/dbs/logo.svg"
LETTERS = [
    "             ▄▄▄▄▄▄▄▄",
    "             █████████▄",
    "             ████  ████",
    "             ████ ▄████",
    "             █████████     ▄▄▄▄▄▄",
    " █████████▄  ████▀▀████  ▄████████",
    " █████▀████  ████  ████  ████ █████",
    " █████ ████▄ ████  ████  ████▄ ▀▀▀",
    " █████ █████ ████  ████  ▀██████▄",
    " █████ █████ ████  ████    ▀▀█████▄",
    " █████ █████ ████  ████  ████ ▀████",
    " █████ ████▀ ████  ████  ████  ████",
    " ██████████  ██████████  ▀████████▀",
    " ▀▀▀▀▀▀▀▀▀   ▀▀▀▀▀▀▀▀▀     ▀▀▀▀▀▀",
]


def test_the_logo_is_drawn_from_the_shipped_drawing():
    drawn = logo.outlines(SHIPPED.read_text())

    assert logo.blocks(drawn, 36, drawn.rows_for(36)) == LETTERS


def test_the_menu_reads_the_same_artwork_as_the_official_logo():
    official = logo.outlines(OFFICIAL.read_text())
    shipped = start.logo()

    assert shipped.shapes == official.shapes
    assert len(shipped.shapes) == 3


def test_the_logo_keeps_its_proportions_at_any_width():
    drawn = start.logo()

    for columns in (16, 22, 36, 60):
        rows = drawn.rows_for(columns)
        assert abs(columns / (rows * 2) - drawn.width / drawn.height) < 0.2


def test_the_logo_is_painted_in_its_own_blue():
    canvas = Canvas(40, 16, theme.BASE)

    layout.logo(canvas, 0, 0, start.logo(), 36, palette.TRUE)

    colours = {style.fg for row in canvas.cells for char, style in row if char == "▀"}
    assert palette.LOGO_BLUE in colours
    assert all(
        palette.luminance(palette.LOGO_BLUE)
        <= palette.luminance(colour)
        <= palette.luminance(theme.SURFACE)
        for colour in colours
    )


def test_with_few_colours_the_logo_is_whole_blocks_in_its_blue():
    canvas = Canvas(40, 16, theme.BASE)

    layout.logo(canvas, 0, 0, start.logo(), 36, palette.BASIC)

    assert canvas.lines()[:14] == LETTERS
