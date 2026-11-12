import pytest
from django.db import connection

from dbs import __version__
from dbs.manager.menu import plain
from dbs.manager.menu.forms import FormScreen

pytestmark = pytest.mark.django_db
MANAGER = ["down"] * 6


@pytest.fixture
def children(monkeypatch):
    started = []
    monkeypatch.setattr(plain, "child", lambda words: started.append(list(words)) or 0)
    return started


def test_the_manager_page_says_where_everything_is_kept(menu, data_dir):
    menu.press(*MANAGER)

    assert __version__ in menu.line_with("Version")
    assert str(data_dir)[-30:] in menu.line_with("Data folder")
    assert connection.vendor in menu.line_with("Database")
    for label in ("Backups", "Secret key", "Log", "Last export"):
        assert menu.line_with(label)


def test_the_database_is_named_without_its_password(menu, settings):
    menu.press(*MANAGER)

    assert "password" not in menu.line_with("Database").lower()


def test_the_page_shows_the_logo_where_there_is_room(open_menu, admin):
    menu = open_menu(admin, columns=140, rows=40)

    menu.press(*MANAGER)

    assert menu.screen.count("▀") > 300


def test_starting_the_manager_leaves_the_screen_and_comes_back(menu, children):
    menu.press(*MANAGER, "enter", "enter")
    assert isinstance(menu.app.top, FormScreen) and "Port" in menu.screen

    menu.press(*["down"] * 10, "enter")

    assert children == [["run"]]
    assert "django_dbs run" in menu.printed
    assert menu.terminal.paused == ["\nPress Enter to return to the menu. "]
    assert not menu.app.closed


def test_an_export_is_the_command_with_the_file_chosen(
    menu, children, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)

    menu.press(
        *MANAGER,
        "enter",
        "down",
        "enter",
        "enter",
        "n",
        "manager.dbs",
        "enter",
        "down",
        "space",
        *["down"] * 5,
        "enter",
    )

    assert children == [["export", "--with-backups", str(tmp_path / "manager.dbs")]]


def test_an_import_is_explained_and_not_started(menu, children):
    menu.press(*MANAGER, "enter", "down", "down", "enter", "enter")

    assert children == []
    assert menu.saw("An import replaces the data folder this menu is working in.")


def test_claude_is_given_its_line_to_add(menu, children):
    menu.press(*MANAGER, "enter", "end", "enter", "enter")

    assert children == []
    assert menu.saw("claude mcp add dbs -- django_dbs mcp")


def test_with_one_account_there_is_no_other_to_act_as(menu):
    menu.press(*MANAGER)

    assert "Act as another account" not in menu.screen
