import pytest

from dbs.manager.accounts.services import AccountManagementService
from dbs.manager.applications.repositories import ApplicationRepository
from dbs.manager.menu.forms import FormScreen
from dbs.manager.menu.screens.listing import ListingScreen, ObjectScreen
from tests.manager.servers.support import PASSWORD

pytestmark = pytest.mark.django_db
SECTIONS = [
    "Dashboard",
    "Servers",
    "Applications",
    "Backups",
    "Activity",
    "Accounts",
    "Manager",
    "All commands",
]


@pytest.fixture
def world(make_server, make_application):
    web = make_server("web-1", "10.0.0.5")
    make_server("db-1", "10.0.0.9")
    return {
        "shop": make_application("shop", server=web),
        "blog": make_application("blog", server=web),
    }


def account(role, name="vera"):
    return (
        AccountManagementService(None)
        .create(username=name, password=PASSWORD, role=role)
        .user
    )


def test_the_menu_opens_on_the_dashboard_with_its_sections_beside_it(menu):
    lines = menu.screen.splitlines()

    assert "DBS manager 0.8.2" in lines[0] and lines[0].rstrip().endswith(
        "sara · admin"
    )
    assert [
        name for name in SECTIONS if any(f" {name} " in line for line in lines)
    ] == SECTIONS
    assert "▸ Dashboard" in menu.screen
    assert "No servers yet. Add a server, then the applications it runs." in menu.screen


def test_the_arrows_move_through_the_sections_and_show_each(menu, world):
    menu.press("down")
    assert "▸ Servers" in menu.screen and "deploy@10.0.0.5" in menu.screen

    menu.press("down")
    assert "▸ Applications" in menu.screen and "shop" in menu.screen

    menu.press("up", "up", "up")
    assert "▸ All commands" in menu.screen and "server add" in menu.screen


def test_enter_moves_into_the_page_and_escape_comes_back(menu, world):
    menu.press("down", "enter")
    assert not menu.app.in_sidebar and "Enter Open" in menu.screen.splitlines()[-1]

    menu.press("esc")
    assert menu.app.in_sidebar and "q Quit" in menu.screen.splitlines()[-1]


def test_tab_moves_between_the_sections_and_the_page(menu, world):
    menu.press("tab")
    assert not menu.app.in_sidebar

    menu.press("tab")
    assert menu.app.in_sidebar


def test_q_leaves_the_menu(menu):
    menu.press("q")

    assert menu.app.closed


def test_control_c_leaves_the_menu(menu):
    menu.press("ctrl+c")

    assert menu.app.closed


def test_the_question_mark_shows_the_keys(menu):
    menu.press("?", "enter")

    assert menu.saw("Arrow keys move.") and "Arrow keys move." not in menu.screen


def test_the_dashboard_lists_each_server_with_its_applications_and_their_state(
    menu, world
):
    menu.press("enter", "r")

    assert "Servers 2" in menu.screen and "Applications 2" in menu.screen
    assert "○ Not seen yet" in menu.line_with("web-1") and "10.0.0.5" in menu.line_with(
        "web-1"
    )
    assert "○ Not checked" in menu.line_with(
        "  shop"
    ) and "on the server" in menu.line_with("  shop")
    assert "none yet" in menu.line_with("  blog") and "no plan" in menu.line_with(
        "  blog"
    )


def test_the_dashboard_reminds_to_export_once_there_is_something_to_lose(menu, world):
    menu.press("enter", "r")

    assert "Export the manager's data" in menu.screen


def test_a_row_of_the_dashboard_opens_what_can_be_done_with_it(menu, world):
    menu.press("enter", "r", "down", "down", "enter")

    assert isinstance(menu.app.top, ObjectScreen)
    assert (
        "Back up now" in menu.screen
        and "Schedule" in menu.screen
        and "Files" in menu.screen
    )


def test_a_list_shows_a_state_as_a_symbol_and_a_word_and_leaves_the_id_out(menu, world):
    menu.press("down", "enter")

    header = menu.line_with("Name")
    assert "Status" in header and "Id" not in header
    assert "○ Not checked" in menu.line_with("web-1")
    assert str(world["shop"].server.pk) not in menu.screen


def test_a_list_is_filtered_as_it_is_typed(menu, world):
    menu.press("down", "enter", "/", "db")

    assert "db-1" in menu.screen and "web-1" not in menu.screen
    assert "Filter: db" in menu.screen

    menu.press("esc")
    assert "web-1" in menu.screen


def test_a_filter_that_matches_nothing_says_so(menu, world):
    menu.press("down", "enter", "/", "zzz")

    assert "Nothing matches." in menu.screen


def test_a_opens_the_form_that_adds_one(menu):
    menu.press("down", "enter", "a")

    assert isinstance(menu.app.top, FormScreen)
    assert "Add a server" in menu.screen and "Host *" in menu.screen


def test_where_two_things_can_be_added_they_are_offered(menu):
    menu.press("down", "down", "enter", "a", "esc")

    assert menu.saw("Add an application") and menu.saw("Find applications on a server")


def test_the_way_back_is_shown_above_the_page(menu, world):
    menu.press("down", "down", "enter", "enter")

    assert "Applications → blog" in menu.screen


def test_what_a_server_runs_is_listed_from_the_server(menu, world):
    menu.press("down", "enter", "down", "enter", "down", "enter")

    assert isinstance(menu.app.top, ListingScreen)
    assert "web-1 → Applications" in menu.screen
    assert "shop" in menu.screen and "blog" in menu.screen


def test_a_server_that_runs_nothing_says_what_to_do_next(menu, world):
    menu.press("down", "enter", "enter", "down", "enter")

    assert "This server runs no application yet." in menu.screen


def test_an_application_lists_its_own_backups_schedule_and_env_file(menu, world):
    menu.press("down", "down", "enter", "enter", "down", "down", "enter")
    assert "No backups of this application yet." in menu.screen

    menu.press("esc", "down", "enter")
    assert "No plan yet." in menu.screen

    menu.press("esc", "down", "down", "enter")
    assert "No version kept yet." in menu.screen


def test_details_show_what_the_command_shows(menu, world):
    menu.press("down", "down", "enter", "enter", "enter")

    assert "settings module" in menu.screen and "config.settings.prod" in menu.screen
    assert "✓ Done." in menu.screen


def test_removing_from_the_actions_goes_back_to_a_list_without_it(menu, world):
    menu.press(
        "down",
        "down",
        "enter",
        "enter",
        "end",
        "enter",
        "blog",
        "enter",
        PASSWORD,
        "enter",
    )
    assert "Done." in menu.screen

    menu.press("enter")

    assert isinstance(menu.app.top, ListingScreen)
    assert (
        "shop" in menu.screen and "blog" not in menu.screen.split("Applications", 2)[-1]
    )
    assert not ApplicationRepository().active().filter(name="blog").exists()


def test_an_application_renamed_by_an_edit_is_acted_on_under_its_new_name(menu, world):
    menu.press("down", "down", "enter", "enter")
    page = menu.app.top
    to_edit = [row.cells[0] for row in page.view.rows].index("Edit")

    menu.press(
        *["down"] * to_edit, "enter", "journal", *["down"] * 30, "enter", "enter"
    )

    assert menu.app.top is page and page.reference == "journal"
    assert "Applications → journal" in menu.screen


def test_a_page_whose_application_is_gone_closes_when_it_is_returned_to(menu, world):
    menu.press("down", "down", "enter", "enter", "enter")
    assert "✓ Done." in menu.screen
    ApplicationRepository().active().filter(name="blog").delete()

    menu.press("enter")

    assert isinstance(menu.app.top, ListingScreen)
    assert "shop" in menu.screen and "→ blog" not in menu.screen


def test_the_way_back_names_a_command_once_though_its_form_and_result_share_it(
    menu, world
):
    menu.press(
        "up", "enter", "/", "app show", "enter", "enter", "nope", "down", "enter"
    )

    assert "All commands → app show" in menu.screen and "✗" in menu.screen
    assert "app show → app show" not in menu.screen


def test_a_dangerous_action_is_marked(menu, world):
    menu.press("down", "down", "enter", "enter")
    row = next(row for row in menu.app.top.view.rows if row.cells[0] == "Remove")

    assert row.danger


def test_an_account_is_offered_only_what_its_role_may_do(open_menu, admin, world):
    menu = open_menu(account("viewer"))

    menu.press("down", "down", "enter", "enter")

    offered = [row.cells[0] for row in menu.app.top.view.rows]
    assert offered == [
        "Details",
        "Backups",
        "Schedule",
        "Files",
        ".env file",
        "Activity",
    ]
    assert "a " not in menu.screen.splitlines()[-1].replace("Esc Back", "")


def test_an_operator_backs_up_and_checks_and_changes_nothing_else(
    open_menu, admin, world
):
    menu = open_menu(account("operator"))

    menu.press("down", "down", "enter", "enter")

    offered = [row.cells[0] for row in menu.app.top.view.rows]
    assert "Back up now" in offered and "Check" in offered and "Deploy" in offered
    assert "Edit" not in offered and "Remove" not in offered


def test_activity_opens_an_entry_straight_away(menu, admin, world):
    from dbs.manager.activity.services import ActivityService

    ActivityService(admin).record("server.check", target="web-1")

    menu.press("down", "down", "down", "down", "enter", "enter")

    assert "server.check" in menu.screen and "finished at" in menu.screen


def test_every_command_is_listed_and_filtered(menu):
    menu.press("up", "enter", "/", "backup restore", "enter", "enter")

    assert isinstance(menu.app.top, FormScreen)
    assert "Mode *" in menu.screen


def test_a_window_too_small_asks_for_more_room(open_menu, admin):
    menu = open_menu(admin, columns=50, rows=12)

    assert menu.screen.strip() == "Make this window larger to use the menu."


def test_a_narrow_window_keeps_the_sections_and_drops_the_logo(open_menu, admin):
    menu = open_menu(admin, columns=80, rows=24)

    assert "▀" not in menu.screen and "▸ Dashboard" in menu.screen


def test_a_terminal_without_utf_8_gets_plain_characters(open_menu, admin, world):
    menu = open_menu(admin, unicode=False)

    menu.press("down", "enter")

    assert menu.screen.isascii()
    assert "> Servers" in menu.screen and "o Not checked" in menu.screen
    assert "Up/Down Move" in menu.screen.splitlines()[-1]


def test_what_is_cut_short_is_marked_in_plain_characters_too(open_menu, admin, world):
    menu = open_menu(admin, columns=66, rows=20, unicode=False)

    menu.press("down", "enter")

    assert "..." in menu.screen and menu.screen.isascii()


def test_no_color_sends_no_colour(open_menu, admin):
    menu = open_menu(admin, environ={"TERM": "xterm-256color", "NO_COLOR": "1"})

    sent = menu.terminal.stream.getvalue()

    assert "38;" not in sent and "48;" not in sent
    assert "\x1b[0;7m" in sent


def test_a_plain_terminal_gets_its_own_colours_and_whole_blocks_for_the_logo(
    open_menu, admin
):
    menu = open_menu(admin, environ={"TERM": "xterm"})

    sent = menu.terminal.stream.getvalue()

    assert "38;2" not in sent and "48;" not in sent
    assert "█" in menu.screen


def test_an_expired_password_is_said_once_the_menu_is_open(open_menu, admin, settings):
    from datetime import timedelta

    from django.utils import timezone

    from dbs.manager.accounts.repositories import AccountRepository

    held = AccountRepository().find(admin.pk) or AccountRepository().find_by_username(
        "sara"
    )
    AccountRepository().update(
        held, password_changed_at=timezone.now() - timedelta(days=400)
    )

    menu = open_menu(admin)

    assert "the password of sara has expired" in menu.screen
    assert "django_dbs password sara" in menu.screen
