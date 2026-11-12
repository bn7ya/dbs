import pytest

from dbs.manager.applications.repositories import ApplicationRepository
from dbs.manager.menu import commands, running
from dbs.manager.servers.repositories import ServerRepository
from dbs.manager.servers.services import ServerConnectionService
from tests.manager.servers.support import PASSWORD, SSH_PASSWORD

pytestmark = pytest.mark.django_db
STOPPED = "Stopped; nothing was changed."


def run(menu, *path, **values):
    return running.run(menu.app, commands.verb(*path), values)


def queue(menu, *presses):
    menu.queue(*presses)


def adding(menu, **values):
    return run(
        menu,
        "server",
        "add",
        **{"<name>": "web-1", "--host": "10.0.0.5", "--user": "deploy", **values},
    )


def test_a_yes_trusts_the_offered_key_and_the_secret_is_asked_in_a_dialog(
    menu, admin, offered, remote
):
    queue(menu, "y", SSH_PASSWORD, "enter")

    outcome = adding(menu, **{"--ssh-password": True})

    assert outcome.ok, outcome.problem
    assert ServerRepository().active().get(name="web-1").host_key == offered
    assert menu.saw("SSH password")
    assert SSH_PASSWORD not in "".join(menu.frames)


def test_a_secret_the_form_already_holds_is_not_asked_again(
    menu, admin, offered, remote
):
    queue(menu, "y")

    outcome = running.run(
        menu.app,
        commands.verb("server", "add"),
        {
            "<name>": "web-1",
            "--host": "10.0.0.5",
            "--user": "deploy",
            "--ssh-password": True,
        },
        answers={"SSH password": SSH_PASSWORD},
    )

    assert outcome.ok, outcome.problem
    server = ServerRepository().active().get(name="web-1")
    assert ServerConnectionService(admin).credentials(server).password == SSH_PASSWORD
    assert not menu.saw("SSH password")


def test_the_question_is_asked_over_what_the_command_already_printed(
    menu, offered, remote
):
    queue(menu, "n")

    adding(menu, **{"--generate-key": True})

    asked = [frame for frame in menu.frames if "Is this the server's key?" in frame]
    assert asked and all("offers ssh-ed25519" in frame for frame in asked)
    assert "[y/N]" not in "".join(asked)


def test_a_no_stops_the_command_and_changes_nothing(menu, offered, remote):
    queue(menu, "n")

    outcome = adding(menu, **{"--generate-key": True})
    menu.press()

    assert not outcome.ok and STOPPED in menu.screen
    assert not ServerRepository().active().exists()


def test_escape_at_a_question_is_a_no(menu, offered, remote):
    queue(menu, "esc")

    outcome = adding(menu, **{"--generate-key": True})

    assert outcome.problem == "stopped; nothing was changed."


def test_removing_asks_for_the_name_typed_out_then_the_password(menu, make_application):
    application = make_application(name="shop")
    queue(menu, "shop", "enter", PASSWORD, "enter")

    outcome = run(menu, "app", "remove", **{"<application>": "shop"})

    assert outcome.ok, outcome.problem
    assert menu.saw("Type the application's name (shop) to remove it:")
    assert menu.saw("Password for sara")
    assert not ApplicationRepository().active().filter(pk=application.pk).exists()


def test_another_name_typed_stops_before_the_password_is_asked(menu, make_application):
    application = make_application(name="shop")
    queue(menu, "blog", "enter")

    outcome = run(menu, "app", "remove", **{"<application>": "shop"})

    assert not outcome.ok and not menu.saw("Password for sara")
    assert ApplicationRepository().active().filter(pk=application.pk).exists()


def test_escape_at_the_password_stops_the_command(menu, make_application):
    application = make_application(name="shop")
    queue(menu, "shop", "enter", "esc")

    outcome = run(menu, "app", "remove", **{"<application>": "shop"})

    assert outcome.problem == "stopped; nothing was changed."
    assert ApplicationRepository().active().filter(pk=application.pk).exists()


def test_an_empty_password_is_refused_as_the_command_refuses_it(menu, make_application):
    make_application(name="shop")
    queue(menu, "shop", "enter", "enter")

    outcome = run(menu, "app", "remove", **{"<application>": "shop"})

    assert outcome.problem == "the password is empty."


def test_a_wrong_password_is_the_commands_refusal(menu, make_application):
    application = make_application(name="shop")
    queue(menu, "shop", "enter", "not-the-password", "enter")

    outcome = run(menu, "app", "remove", **{"<application>": "shop"})

    assert not outcome.ok and "password" in outcome.problem.lower()
    assert ApplicationRepository().active().filter(pk=application.pk).exists()


def test_the_password_is_typed_masked_and_never_drawn(menu, make_application):
    make_application(name="shop")
    queue(menu, "shop", "enter", PASSWORD, "enter")

    run(menu, "app", "remove", **{"<application>": "shop"})

    assert PASSWORD not in "".join(menu.frames)
    assert menu.saw("•" * len(PASSWORD))


def test_the_password_is_asked_again_for_the_next_command(menu, make_application):
    make_application(name="shop")
    make_application(name="blog", host="10.0.0.6")
    queue(menu, "shop", "enter", PASSWORD, "enter")
    run(menu, "app", "remove", **{"<application>": "shop"})
    asked = sum("Password for sara" in frame for frame in menu.frames)
    queue(menu, "blog", "enter", PASSWORD, "enter")

    outcome = run(menu, "app", "remove", **{"<application>": "blog"})

    assert outcome.ok
    assert sum("Password for sara" in frame for frame in menu.frames) > asked
