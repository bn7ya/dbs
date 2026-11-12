import pytest

from dbs.manager.backups.models import BackupFile, BackupPlan
from dbs.manager.envfiles.models import EnvVersion
from dbs.manager.menu import commands, pickers
from dbs.manager.menu.forms import FormScreen

pytestmark = pytest.mark.django_db
RUNS_JOBS = pytest.mark.django_db(transaction=True)


def form(menu, *path, values=None):
    screen = FormScreen(menu.app, commands.verb(*path), values)
    menu.app.push(screen)
    menu.press()
    return screen


def test_a_row_is_named_by_its_name_while_no_other_shares_it():
    rows = [
        {"id": "1", "name": "shop"},
        {"id": "2", "name": "blog"},
        {"id": "3", "name": "shop"},
    ]

    assert pickers.reference(rows[1], rows) == "blog"
    assert pickers.reference(rows[0], rows) == "1"
    assert pickers.reference({"id": 7}, rows) == "7"


def test_the_rows_of_a_list_are_what_the_list_command_gives(menu, make_server):
    make_server("web-1", "10.0.0.5")

    found = pickers.rows(menu.app, ("server", "list"))

    assert [row["name"] for row in found] == ["web-1"]
    assert found[0]["host"] == "10.0.0.5"


def test_an_empty_list_says_so_and_leaves_the_field(menu):
    screen = form(menu, "env", "compare")

    menu.press("enter", "enter")

    assert menu.saw("Choose an application") and menu.saw("Nothing to choose from.")
    assert screen.collected()["<version>"] == ""


@RUNS_JOBS
def test_a_backup_is_chosen_from_the_backups_and_filled_in_by_its_number(
    menu, host, two_applications
):
    from dbs.manager.menu import running

    running.run(menu.app, commands.verb("backup", "take"), {"--all": True}, quiet=True)
    newest = BackupFile.objects.order_by("-created_at").first()
    screen = form(menu, "backup", "restore")

    menu.press("enter", "enter")

    assert menu.saw("Choose a backup")
    assert screen.collected()["<backup>"] in {
        str(file.pk) for file in BackupFile.objects.all()
    }
    assert newest is not None


def test_a_plan_is_chosen_by_its_name_and_filled_in_by_its_number(
    menu, make_application
):
    plan = BackupPlan.objects.create(
        application=make_application(name="shop"), name="nightly", kind="dbs"
    )
    screen = form(menu, "plan", "run")

    menu.press("enter", "enter")

    assert menu.saw("nightly") and screen.collected()["<plan>"] == str(plan.pk)


def test_a_version_of_the_env_file_asks_which_application_first(
    menu, application, local_host
):
    from dbs.manager.menu import running

    running.run(
        menu.app, commands.verb("env", "pull"), {"<application>": "web-1"}, quiet=True
    )
    screen = form(menu, "env", "reveal")

    menu.press("enter", "enter", "enter")

    assert menu.saw("Choose an application") and menu.saw(
        "Choose a version of the .env file"
    )
    assert screen.collected()["<version>"] == str(EnvVersion.objects.get().pk)


def test_an_entry_of_the_activity_is_chosen_by_what_happened(menu, admin):
    from dbs.manager.activity.services import ActivityService

    entry = ActivityService(admin).record("server.check", target="web-1")
    screen = form(menu, "activity", "show")

    menu.press("enter", "enter")

    assert menu.saw("server.check") and screen.collected()["<entry>"] == str(entry.pk)


def test_an_account_is_chosen_from_the_accounts(menu, admin):
    screen = form(menu, "password")

    menu.press("enter", "enter")

    assert screen.collected()["<name>"] == "sara"


def test_a_folder_on_a_server_waits_for_the_server_to_be_chosen(menu):
    screen = form(menu, "app", "add")

    menu.press("down", "down", "enter", "enter")

    assert menu.saw("Choose the server first.")
    assert screen.collected()["--folder"] == ""


def test_a_folder_on_a_server_is_chosen_in_the_explorer(
    menu, make_server, local_host, project
):
    make_server("web-1", "10.0.0.5")
    screen = form(
        menu, "app", "add", values={"--server": "web-1", "--folder": str(project)}
    )

    menu.press("down", "down", "enter", "s")

    assert menu.saw("Choose a folder on the server")
    assert screen.collected()["--folder"] == str(project)


def test_a_file_on_this_computer_is_chosen_in_the_explorer(menu, tmp_path, monkeypatch):
    (tmp_path / "id_ed25519").write_text("key")
    monkeypatch.chdir(tmp_path)
    screen = form(menu, "server", "add")

    menu.press(*["down"] * 4, "enter", "enter")

    assert menu.saw("Choose a file on this computer")
    assert screen.collected()["--key-file"] == str(tmp_path / "id_ed25519")


def test_every_kind_of_argument_that_names_something_has_its_list():
    from dbs.manager.menu import meanings

    kinds = {
        meaning.kind
        for known in (meanings.COMMON, *meanings.SPECIFIC.values())
        for meaning in known.values()
    }

    assert kinds - {meanings.TEXT} == set(pickers.PICKERS)
