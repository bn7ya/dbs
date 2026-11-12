import re

from dbs.manager.menu.kit import theme
from dbs.manager.menu.kit.canvas import Area, Canvas, Painter
from dbs.manager.menu.kit.palette import TRUE

MOVE = re.compile(r"\x1b\[(\d+);(\d+)H")
OTHER = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


class Display:
    def __init__(self, columns, rows):
        self.cells = [[" "] * columns for _ in range(rows)]
        self.x = self.y = 0

    def take(self, sent):
        index = 0
        while index < len(sent):
            move = MOVE.match(sent, index)
            other = OTHER.match(sent, index)
            if move:
                self.y, self.x = int(move.group(1)) - 1, int(move.group(2)) - 1
                index = move.end()
            elif other:
                if other.group().endswith("2J"):
                    self.cells = [[" "] * len(row) for row in self.cells]
                index = other.end()
            else:
                self.cells[self.y][self.x] = sent[index]
                self.x += 1
                index += 1

    def lines(self):
        return ["".join(row).rstrip() for row in self.cells]


def test_what_the_painter_sends_rebuilds_the_canvas():
    canvas = Canvas(20, 4, theme.BASE)
    canvas.put(2, 1, "servers", theme.HEADING)
    canvas.put(0, 3, "q Quit", theme.HINT)
    display = Display(20, 4)

    display.take(Painter(TRUE).paint(canvas))

    assert display.lines() == canvas.lines()


def test_a_second_frame_sends_only_what_changed():
    painter = Painter(TRUE)
    first = Canvas(20, 4, theme.BASE)
    first.put(0, 0, "shop")
    display = Display(20, 4)
    display.take(painter.paint(first))
    second = Canvas(20, 4, theme.BASE)
    second.put(0, 0, "shop")
    second.put(0, 2, "blog")

    sent = painter.paint(second)
    display.take(sent)

    assert "shop" not in sent and "blog" in sent
    assert display.lines() == second.lines()


def test_an_unchanged_frame_sends_no_text():
    painter = Painter(TRUE)
    canvas = Canvas(10, 2, theme.BASE)
    canvas.put(0, 0, "same")
    painter.paint(canvas)

    assert OTHER.sub("", painter.paint(canvas)) == ""


def test_a_new_size_repaints_everything():
    painter = Painter(TRUE)
    small = Canvas(10, 2, theme.BASE)
    small.put(0, 0, "shop")
    painter.paint(small)
    large = Canvas(12, 3, theme.BASE)
    large.put(0, 0, "shop")

    assert "shop" in painter.paint(large)


def test_text_is_cut_at_the_edge_and_never_wraps():
    canvas = Canvas(6, 2, theme.BASE)

    canvas.put(3, 0, "abcdef")

    assert canvas.lines() == ["   abc", ""]


def test_text_is_cut_at_its_limit_with_an_ellipsis():
    canvas = Canvas(20, 1, theme.BASE)

    canvas.put(0, 0, "a-long-backup-name", limit=8)

    assert canvas.lines() == ["a-long-…"]


def test_a_wide_character_takes_two_cells():
    canvas = Canvas(6, 1, theme.BASE)

    end = canvas.put(0, 0, "日本")

    assert end == 4
    assert canvas.cells[0][1][0] == "" and canvas.cells[0][2][0] == "本"


def test_control_characters_never_reach_the_canvas():
    canvas = Canvas(12, 1, theme.BASE)

    canvas.put(0, 0, "a\x1b[2Jb")

    assert "\x1b" not in canvas.text()


def test_the_cursor_is_shown_only_where_asked():
    painter = Painter(TRUE)
    canvas = Canvas(10, 2, theme.BASE)

    assert "\x1b[?25h" not in painter.paint(canvas)
    assert painter.paint(canvas, (3, 1)).endswith("\x1b[2;4H\x1b[?25h")


def test_an_area_is_inset_and_split_into_rows():
    area = Area(0, 0, 20, 10).inset(1, 2, 1, 1)

    assert (area.x, area.y, area.columns, area.rows) == (1, 2, 18, 7)
    assert area.row(1).y == 3 and area.row(1).rows == 1
