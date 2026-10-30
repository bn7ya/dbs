import re
from pathlib import Path

import pytest

from dbs.manager import spa

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL = ROOT / "docs" / "assets" / "dbs-logo.svg"
COPIES = (
    ROOT / "manager-ui" / "public" / "logo.svg",
    ROOT / "manager-ui" / "public" / "favicon.svg",
    ROOT / "dbs" / "static" / "dbs" / "logo.svg",
    ROOT / "dbs" / "static" / "dbs" / "favicon.svg",
)
VIEW_BOX = re.compile(r'viewBox="([^"]*)"')


def artwork(path: Path) -> str:
    return VIEW_BOX.sub("", path.read_text(encoding="utf-8"))


def view_box(path: Path) -> list[float]:
    return [float(part) for part in VIEW_BOX.search(path.read_text(encoding="utf-8")).group(1).split()]


def test_the_original_logo_is_the_whole_canvas_the_developer_drew():
    assert view_box(ORIGINAL) == [0, 0, 2000, 2000]
    assert "<script" not in ORIGINAL.read_text(encoding="utf-8")


@pytest.mark.parametrize("copy", COPIES, ids=lambda path: str(path.relative_to(ROOT)))
def test_every_shipped_logo_is_the_same_artwork_framed_around_the_letters(copy):
    assert artwork(copy) == artwork(ORIGINAL)
    x, y, width, height = view_box(copy)
    assert (x, y) > (0, 0) and x + width < 2000 and y + height < 2000


def test_the_favicon_is_square_and_its_name_is_never_cached_as_hashed():
    _, _, width, height = view_box(ROOT / "manager-ui" / "public" / "favicon.svg")

    assert width == height
    assert not spa.HASHED.search("favicon.svg")
    assert not spa.HASHED.search("logo.svg")
