import pytest

from dbs.manager.backups.models import BackupPlan
from dbs.manager.menu import commands, forms, plain
from dbs.manager.menu.forms import FormScreen
from dbs.manager.servers.repositories import ServerRepository
from dbs.manager.servers.services import ServerConnectionService
from tests.manager.servers.support import SSH_PASSWORD

pytestmark = pytest.mark.django_db
TO_THE_BUTTON = ["down"] * 30


def form(menu, *path, values=None, fixed=()):
    screen = FormScreen(menu.app, commands.verb(*path), values, fixed=fixed)
    menu.app.push(screen)
    menu.press()
    return screen


def test_a_form_has_a_field_for_each_argument_and_marks_what_is_needed(menu):
    form(menu, "server", "add")

    for label in ("Name *", "Host *", "User *", "Port", "Key file", "Host key"):
        assert label in menu.screen
    assert "SSH password" in menu.screen
    assert "Generate a new key" in menu.screen


def test_a_form_leaves_out_what_only_a_script_needs(menu):
    form(menu, "server", "add")

    for label in ("Json", "As ", "Yes", "Data dir", "Database url", "stdin"):
        assert label not in menu.screen


def test_what_is_typed_goes_into_the_field_and_into_the_command_shown(menu):
    form(menu, "server", "add")

    menu.press("web-1", "down", "10.0.0.5")

    assert "Runs: django_dbs server add --host=10.0.0.5 web-1" in menu.screen


def test_an_empty_field_says_what_the_command_uses_instead(menu):
    form(menu, "activity", "list")

    assert "20 if left empty" in menu.line_with("Limit")

    menu.press(*["down"] * 4, "5")
    assert "if left empty" not in menu.line_with("Limit")


def test_a_field_is_edited_in_place(menu):
    screen = form(menu, "server", "add")

    menu.press("web-11", "backspace", "home", "delete", "x")

    assert screen.collected()["<name>"] == "xeb-1"


def test_running_without_what_is_needed_names_it_and_runs_nothing(menu):
    form(menu, "server", "add")

    menu.press(*TO_THE_BUTTON, "enter")

    assert "Name is needed." in menu.screen
    assert isinstance(menu.app.top, FormScreen)


def test_a_server_needs_one_way_to_sign_in_before_its_key_is_asked_about(menu):
    form(
        menu,
        "server",
        "add",
        values={"<name>": "web-1", "--host": "10.0.0.5", "--user": "deploy"},
    )

    menu.press(*TO_THE_BUTTON, "enter")

    assert "Choose how to sign in" in menu.screen
    assert not menu.saw("Is this the server's key?")


def to_field(screen, key):
    return ["down"] * [argument.key for argument in screen.fields].index(key)


def test_the_ssh_password_is_typed_in_the_form_masked_and_signs_in(
    menu, admin, offered, remote
):
    screen = form(
        menu,
        "server",
        "add",
        values={"<name>": "web-1", "--host": "10.0.0.5", "--user": "deploy"},
    )

    menu.press(*to_field(screen, "--ssh-password"), SSH_PASSWORD)
    assert "•" * len(SSH_PASSWORD) in menu.line_with("SSH password")
    assert menu.line_with("Runs:").rstrip(" │").endswith("--ssh-password web-1")

    menu.press(*TO_THE_BUTTON, "enter", "y")

    server = ServerRepository().active().get(name="web-1")
    assert ServerConnectionService(admin).credentials(server).password == SSH_PASSWORD
    assert "Added web-1." in menu.screen
    assert SSH_PASSWORD not in "".join(menu.frames)


def test_a_form_shows_a_field_for_each_secret_its_command_takes(menu):
    form(menu, "server", "add")
    assert "SSH password" in menu.screen and "Passphrase of the key file" in menu.screen
    assert "[ ] No" not in menu.line_with("SSH password")

    form(menu, "app", "add")
    assert "Backup passphrase" in menu.screen


def test_a_secret_typed_in_a_form_is_gone_once_the_command_has_run(
    menu, offered, remote
):
    screen = form(
        menu,
        "server",
        "add",
        values={"<name>": "web-1", "--host": "10.0.0.5", "--user": "deploy"},
    )

    menu.press(*to_field(screen, "--ssh-password"), SSH_PASSWORD)
    menu.press(*TO_THE_BUTTON, "enter", "n", "enter")

    assert menu.app.top is screen and not ServerRepository().active().exists()
    assert screen.collected()["--ssh-password"] is False
    assert "•" not in menu.screen


def test_a_secret_left_empty_is_not_given_to_the_command(menu):
    screen = form(menu, "server", "add")

    assert "--ssh-password" not in menu.line_with("Runs:")
    assert screen.collected()["--ssh-password"] is False


def test_a_switch_turns_on_and_off_with_space_or_enter(menu):
    screen = form(menu, "backup", "take")

    menu.press("down", "space")
    assert screen.collected()["--all"] is True and "[x] Yes" in menu.screen

    menu.press("enter")
    assert screen.collected()["--all"] is False and "[ ] No" in menu.screen


def test_a_choice_is_stepped_through_with_the_arrows(menu):
    screen = form(
        menu, "backup", "restore", values={"<backup>": "1"}, fixed=["<backup>"]
    )

    menu.press("right")
    assert screen.collected()["--mode"] == "replace"

    menu.press("right")
    assert screen.collected()["--mode"] == "merge"


def test_a_choice_is_picked_from_its_list_with_enter(menu):
    screen = form(
        menu, "backup", "restore", values={"<backup>": "1"}, fixed=["<backup>"]
    )

    menu.press("enter", "down", "enter")

    assert screen.collected()["--mode"] == "replace"
    assert menu.saw("merge") and menu.saw("replace")


def test_a_choice_that_is_not_needed_can_be_left_unset(menu):
    screen = form(menu, "activity", "list")

    menu.press("down", "down", "down", "enter", "down", "enter")
    assert screen.collected()["--status"] == "queued"

    menu.press("enter", "home", "enter")
    assert screen.collected()["--status"] == ""
    assert "--status" not in menu.line_with("Runs:")


def test_what_the_command_would_refuse_is_said_in_the_form(menu):
    form(menu, "activity", "list")

    menu.press("down", "down", "down", "down", "many", *TO_THE_BUTTON, "enter")

    assert "invalid int value: 'many'" in menu.screen
    assert isinstance(menu.app.top, FormScreen)


def test_a_server_is_chosen_from_the_list_of_servers(menu, make_server):
    make_server("web-1", "10.0.0.5")
    make_server("db-1", "10.0.0.9")
    screen = form(menu, "app", "add")

    menu.press("down", "enter", "down", "enter")

    assert menu.saw("Choose a server") and menu.saw("deploy@10.0.0.9")
    assert screen.collected()["--server"] == "web-1"


def test_a_name_can_be_typed_where_a_list_is_offered(menu):
    screen = form(menu, "app", "add")

    menu.press("down", "web-1")

    assert screen.collected()["--server"] == "web-1"


def test_leaving_a_list_keeps_the_field_as_it_was(menu, make_server):
    make_server("web-1", "10.0.0.5")
    screen = form(menu, "app", "add", values={"--server": "db-9"})

    menu.press("down", "enter", "esc")

    assert screen.collected()["--server"] == "db-9"


def test_several_applications_are_marked_in_one_list(menu, make_application):
    make_application(name="shop", host="10.0.0.5")
    make_application(name="blog", host="10.0.0.6")
    screen = form(menu, "backup", "take")

    menu.press("enter", "space", "down", "space", "enter")

    assert screen.collected()["<applications>"] == ["blog", "shop"]
    assert "blog, shop" in menu.screen


def test_values_given_more_than_once_are_added_and_removed_one_by_one(menu):
    screen = form(
        menu, "plan", "add", values={"<application>": "shop"}, fixed=["<application>"]
    )
    to_paths = ["down", "down"]

    menu.press(
        *to_paths,
        "enter",
        "enter",
        "/srv/media",
        "enter",
        "enter",
        "/srv/static",
        "enter",
        "end",
        "enter",
    )
    assert screen.collected()["--path"] == ["/srv/media", "/srv/static"]

    menu.press("enter", "home", "enter", "end", "enter")
    assert screen.collected()["--path"] == ["/srv/static"]


def test_what_was_filled_in_for_the_developer_is_in_the_command_and_not_a_field(menu):
    screen = form(
        menu, "plan", "add", values={"<application>": "shop"}, fixed=["<application>"]
    )

    assert "<application>" not in [argument.key for argument in screen.fields]
    assert "django_dbs plan add shop" in menu.line_with("Runs:")


def test_a_form_longer_than_the_window_scrolls(open_menu, admin):
    menu = open_menu(admin, rows=22)
    form(menu, "app", "add")
    assert "File root" not in menu.screen

    menu.press(*TO_THE_BUTTON)

    assert "File root" in menu.screen and "Name *" not in menu.screen


def test_escape_leaves_the_form_and_runs_nothing(menu):
    form(menu, "server", "add")

    menu.press("web-1", "esc")

    assert not isinstance(menu.app.top, FormScreen)
    assert not menu.saw("Done.")


def test_after_it_worked_enter_goes_back_past_the_form(menu, make_application):
    make_application(name="shop")
    form(menu, "app", "show")

    menu.press("shop", *TO_THE_BUTTON, "enter")
    assert "Done." in menu.screen and "project dir" in menu.screen

    menu.press("enter")
    assert not isinstance(menu.app.top, FormScreen)


def test_after_it_failed_enter_goes_back_to_the_form_as_it_was_filled(menu):
    screen = form(menu, "app", "show")

    menu.press("nope", *TO_THE_BUTTON, "enter")
    assert "✗" in menu.screen

    menu.press("enter")
    assert menu.app.top is screen and screen.collected()["<application>"] == "nope"


def test_removing_a_plan_asks_first_because_the_command_does_not(
    menu, make_application
):
    application = make_application(name="shop")
    plan = BackupPlan.objects.create(
        application=application, name="nightly", kind="dbs"
    )
    verb = commands.verb("plan", "remove")

    assert forms.launch(menu.queue("n").app, verb, {"<plan>": str(plan.pk)}) is None
    assert BackupPlan.objects.filter(pk=plan.pk).exists()
    assert menu.saw("Remove this plan?")

    outcome = forms.launch(menu.queue("y").app, verb, {"<plan>": str(plan.pk)})
    assert outcome.ok and not BackupPlan.objects.filter(pk=plan.pk).exists()


@pytest.fixture
def children(monkeypatch):
    started = []
    monkeypatch.setattr(plain, "child", lambda words: started.append(list(words)) or 0)
    return started


def test_a_command_of_the_installation_runs_as_itself_outside_the_screen(
    menu, children
):
    outcome = forms.launch(
        menu.app,
        commands.verb("account", "role"),
        {"<name>": "omar", "<role>": "viewer"},
    )

    assert outcome.ok and children == [["account", "role", "omar", "viewer"]]
    assert "django_dbs account role omar viewer" in menu.printed
    assert menu.terminal.paused


def test_an_import_is_named_with_its_reason_and_not_run(menu, children):
    outcome = forms.launch(
        menu.queue("enter").app, commands.verb("import"), {"<file>": "/tmp/export.dbs"}
    )

    assert outcome is None and children == []
    assert menu.saw("replaces the data folder") and menu.saw(
        "django_dbs import /tmp/export.dbs"
    )
