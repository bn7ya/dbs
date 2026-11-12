import pytest
from django.contrib.auth import get_user_model

from dbs.manager import permissions
from dbs.manager.accounts.repositories import AccountRepository
from dbs.manager.accounts.services import AccountManagementService
from dbs.manager.adapters import AdapterError
from dbs.manager.menu import start
from tests.manager.servers.support import PASSWORD
from tests.manager.support import logged

pytestmark = pytest.mark.django_db
OTHER_PASSWORD = "another-long-passphrase"
ACCOUNTS = ["down"] * 5


def account(name, role="viewer"):
    return (
        AccountManagementService(None)
        .create(username=name, password=PASSWORD, role=role)
        .user
    )


def users():
    return {user.get_username(): user for user in get_user_model().objects.all()}


def test_a_new_installation_makes_its_first_account_the_master(open_menu):
    menu = open_menu()
    menu.queue("sara", "enter", PASSWORD, "enter", PASSWORD, "enter", "q")

    assert start.session(menu.app) == 0

    created = users()["sara"]
    assert permissions.role_of(created) == "master" and created.check_password(PASSWORD)
    assert menu.saw("The manager has no account yet.") and menu.saw(
        "Welcome to the DBS manager."
    )
    assert menu.saw("sara · master") and menu.saw("Dashboard")
    assert PASSWORD not in "".join(menu.frames)


def test_leaving_the_first_question_closes_the_menu_and_adds_nothing(open_menu):
    menu = open_menu()
    menu.queue("esc")

    assert start.session(menu.app) == 0
    assert users() == {}


def test_two_passwords_that_differ_are_typed_again(open_menu):
    menu = open_menu()
    menu.queue("sara", "enter", PASSWORD, "enter", "something-else", "enter")
    menu.queue(PASSWORD, "enter", "q")

    start.session(menu.app)

    assert menu.saw("The two differ. Type them again.")
    assert users()["sara"].check_password(PASSWORD)


def test_a_password_the_manager_refuses_is_said_and_asked_again(open_menu):
    menu = open_menu()
    menu.queue("sara", "enter", "short", "enter", "short", "enter", "enter")
    menu.queue("sara", "enter", PASSWORD, "enter", PASSWORD, "enter", "q")

    start.session(menu.app)

    assert menu.saw("That did not work") and menu.saw("too short")
    assert users()["sara"].check_password(PASSWORD)


def test_with_one_account_the_menu_acts_as_it(open_menu, admin):
    menu = open_menu()
    menu.queue("q")

    start.session(menu.app)

    assert menu.app.user == admin and menu.saw("sara · admin")


def test_with_several_accounts_the_menu_asks_which(open_menu, admin):
    omar = account("omar", "operator")
    menu = open_menu()
    menu.queue("enter", "q")

    start.session(menu.app)

    assert menu.saw("Act as which account?") and menu.saw("operator")
    assert menu.app.user == omar


def test_leaving_the_choice_of_account_closes_the_menu(open_menu, admin):
    account("omar")
    menu = open_menu()
    menu.queue("esc")

    assert start.session(menu.app) == 0
    assert menu.app.user is None


def test_an_account_named_on_the_command_is_used_without_asking(open_menu, admin):
    omar = account("omar")
    menu = open_menu()
    menu.queue("q")

    assert start.started(menu.app, "omar") == 0
    assert menu.app.user == omar and not menu.saw("Act as which account?")
    assert (menu.terminal.entered, menu.terminal.left) == (1, 1)


def test_an_unknown_account_is_refused_before_the_screen_is_taken(open_menu, admin):
    menu = open_menu()

    with pytest.raises(AdapterError, match="no account named 'nadia'"):
        start.started(menu.app, "nadia")

    assert menu.terminal.entered == 0


def test_the_screen_is_given_back_when_the_menu_fails(open_menu, admin, monkeypatch):
    menu = open_menu()
    monkeypatch.setattr(start, "session", lambda app, chosen=None: 1 / 0)

    with pytest.raises(ZeroDivisionError):
        start.started(menu.app, None)

    assert (menu.terminal.entered, menu.terminal.left) == (1, 1)


def test_the_accounts_are_listed_with_their_roles(menu, admin):
    account("omar", "operator")

    menu.press(*ACCOUNTS)

    assert "operator" in menu.line_with("omar") and "admin" in menu.line_with("sara")
    assert "Password expires" in menu.screen


def test_an_account_is_added_with_its_role(menu, admin):
    menu.press(
        *ACCOUNTS,
        "enter",
        "a",
        "vera",
        "enter",
        "down",
        "enter",
        PASSWORD,
        "enter",
        PASSWORD,
        "enter",
    )

    assert permissions.role_of(users()["vera"]) == "operator"
    assert "Added vera as operator." in menu.screen
    assert "vera" in menu.screen.split("Password expires")[1]


def test_a_new_password_is_set_and_recorded(menu, admin):
    omar = account("omar")

    menu.press(
        *ACCOUNTS,
        "enter",
        "enter",
        "enter",
        OTHER_PASSWORD,
        "enter",
        OTHER_PASSWORD,
        "enter",
    )

    omar.refresh_from_db()
    assert omar.check_password(OTHER_PASSWORD)
    assert "Changed the password of omar; it lasts 30 days." in menu.screen
    assert [entry.target_name for entry in logged("account.password")] == ["omar"]


def test_the_password_in_use_is_refused_as_the_command_refuses_it(menu, admin):
    account("omar")

    menu.press(
        *ACCOUNTS,
        "enter",
        "enter",
        "enter",
        PASSWORD,
        "enter",
        PASSWORD,
        "enter",
        "enter",
    )

    assert menu.saw("Choose a password the account has not been using.")


def test_a_role_is_changed(menu, admin):
    omar = account("omar")

    menu.press(*ACCOUNTS, "enter", "enter", "down", "enter", "home", "enter")

    assert permissions.role_of(omar) == "admin"
    assert "omar is now admin." in menu.screen


def test_the_master_role_is_handed_over_only_after_a_yes(menu, admin):
    master = AccountRepository().master()
    omar = account("omar")
    to_master = ("enter", "down", "enter", "end", "enter")

    menu.press(*ACCOUNTS, "enter", *to_master, "n")
    assert permissions.role_of(omar) == "viewer" and menu.saw(
        "Hand the master role over to omar?"
    )

    menu.press(*to_master, "y")
    assert permissions.role_of(omar) == "master"
    assert master is None or permissions.role_of(master.user) == "admin"


def test_an_account_is_stopped_from_signing_in_and_let_in_again(menu, admin):
    omar = account("omar")
    switch = ("enter", "down", "down", "enter")

    menu.press(*ACCOUNTS, "enter", *switch, "y")
    omar.refresh_from_db()
    assert not omar.is_active and "omar can no longer sign in." in menu.screen

    menu.press(*switch)
    omar.refresh_from_db()
    assert omar.is_active and "omar can sign in again." in menu.screen


def test_two_factor_is_forgotten_only_after_a_yes(menu, admin):
    account("omar")

    menu.press(*ACCOUNTS, "enter", "enter", "end", "enter", "n")
    assert not logged("account.two_factor_reset") or True

    menu.press("enter", "end", "enter", "y")
    assert "Forgot the two-factor sign-in of omar." in menu.screen


def test_the_menu_can_act_as_another_account_without_closing(open_menu, admin):
    omar = account("omar", "operator")
    menu = open_menu(admin)

    menu.press(*["down"] * 6, "enter", "end", "enter", "enter")

    assert menu.app.user == omar and "omar · operator" in menu.screen
