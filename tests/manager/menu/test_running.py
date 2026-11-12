import sys

import pytest

from dbs import audit
from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.backups.models import BackupFile
from dbs.manager import conf
from dbs.manager.menu import commands, running
from dbs.manager.terminal import CommandFailed

RUNS_JOBS = pytest.mark.django_db(transaction=True)
APPLICATIONS = ("down", "down", "enter")
BACK_UP_NOW = ("enter", "down", "enter")


@RUNS_JOBS
def test_a_backup_taken_from_the_menu_is_the_commands_backup(
    menu, admin, host, two_applications
):
    menu.press(*APPLICATIONS, *BACK_UP_NOW)

    assert "Done." in menu.screen
    assert "django_dbs backup take blog" in menu.screen
    assert "blog" in menu.line_with("ok")
    assert len(host.takes) == 1 and BackupFile.objects.count() == 1
    take = ActivityRepository().filtered(action="backup.take").get()
    assert take.status == audit.SUCCEEDED and take.actor == admin


@RUNS_JOBS
def test_enter_after_a_result_goes_back_to_what_was_open(menu, host, two_applications):
    menu.press(*APPLICATIONS, *BACK_UP_NOW)

    menu.press("enter")

    assert "Back up now" in menu.screen and "Done." not in menu.screen


def run(menu, *path, **values):
    return running.run(menu.app, commands.verb(*path), values)


@pytest.fixture
def handler(monkeypatch):
    def use(behaviour):
        monkeypatch.setattr(running, "handler_of", lambda args: behaviour)

    return use


@pytest.mark.django_db
def test_a_job_started_from_the_menu_runs_in_it_as_a_typed_command_runs_its_own(
    menu, handler, settings
):
    settings.DBS_MANAGER_JOBS_INLINE = False
    seen = []
    handler(lambda session: seen.append(conf.jobs_inline()))

    run(menu, "backup", "take", **{"--all": True})

    assert seen == [True] and not conf.jobs_inline()


@pytest.mark.django_db
def test_a_command_is_handed_the_account_the_menu_acts_as(menu, admin, handler):
    seen = []
    handler(
        lambda session: seen.append((session.user, session.waits, session.out.as_json))
    )

    run(menu, "server", "list")

    assert seen == [(admin, False, False)]


@pytest.mark.django_db
def test_what_a_command_refuses_is_shown_and_the_menu_stays_open(menu):
    outcome = run(menu, "backup", "verify", **{"<backup>": "999"})
    menu.press()

    assert not outcome.ok and outcome.code == 1
    assert "✗" in menu.screen and "999" in menu.screen
    assert not menu.app.closed


@pytest.mark.django_db
def test_control_c_stops_the_command_and_not_the_menu(menu, handler):
    def interrupted(session):
        session.out.line("Backing up shop...")
        raise KeyboardInterrupt

    handler(interrupted)

    outcome = run(menu, "backup", "take", **{"--all": True})
    menu.press()

    assert outcome.stopped and not outcome.ok
    assert "Backing up shop..." in menu.screen and "Stopped." in menu.screen
    assert not menu.app.closed and not menu.app.running


@pytest.mark.django_db
def test_a_fault_in_a_command_is_named_and_the_menu_stays_open(menu, handler):
    def broken(session):
        raise ZeroDivisionError("division by zero")

    handler(broken)

    outcome = run(menu, "server", "list")
    menu.press()

    assert outcome.problem == "ZeroDivisionError: division by zero"
    assert "ZeroDivisionError" in menu.screen and not menu.app.closed


@pytest.mark.django_db
def test_a_failure_is_the_commands_own_message(menu, handler):
    def failed(session):
        raise CommandFailed("the folder is not a Django project.")

    handler(failed)

    run(menu, "server", "list")
    menu.press()

    assert "The folder is not a Django project." in menu.screen


@pytest.mark.django_db
def test_what_a_command_prints_by_itself_never_reaches_the_terminal_raw(
    menu, handler, capsys
):
    def printing(session):
        print("Kept a copy of the database.")
        print("Warning: the password has expired.", file=sys.stderr)
        return 0

    handler(printing)

    with menu.app.capturing():
        outcome = run(menu, "server", "list")
    menu.press()

    written = capsys.readouterr()
    assert written.out == "" and written.err == ""
    assert "Kept a copy of the database." in menu.screen
    assert "Warning: the password has expired." in menu.screen
    assert outcome.ok


@pytest.mark.django_db
def test_a_command_run_quietly_opens_no_page(menu):
    before = list(menu.app.stack)

    outcome = running.run(menu.app, commands.verb("server", "list"), {}, quiet=True)

    assert outcome.ok and menu.app.stack == before
    assert outcome.table().empty.startswith("No servers yet")


@pytest.mark.django_db
def test_a_long_result_scrolls(menu, handler):
    def long(session):
        for number in range(80):
            session.out.line(f"line {number}")
        return 0

    handler(long)
    run(menu, "server", "list")
    menu.press()
    assert "line 79" in menu.screen and "line 0 " not in menu.screen

    menu.press("home")

    assert "line 0" in menu.screen and "line 79" not in menu.screen


@pytest.mark.django_db
def test_output_past_256_kib_is_cut_and_says_so(menu, handler):
    def endless(session):
        for _ in range(400):
            session.out.line("x" * 1024)
        return 0

    handler(endless)

    outcome = run(menu, "server", "list")

    assert outcome.transcript.cut
    assert outcome.transcript.blocks[-1].text.startswith(
        "[the rest of the output was cut"
    )
    assert outcome.transcript.size <= 256 * 1024


@pytest.mark.django_db
def test_showing_a_result_plainly_prints_it_and_waits(menu, handler):
    def keyed(session):
        session.out.line("ssh-ed25519 AAAAC3Nza dbs-manager")
        return 0

    handler(keyed)
    run(menu, "server", "public-key", **{"<server>": "web-1"})

    menu.press("p")

    assert "ssh-ed25519 AAAAC3Nza dbs-manager" in menu.printed
    assert menu.terminal.paused == ["\nPress Enter to return to the menu. "]


@pytest.mark.django_db
def test_a_secret_is_shown_plainly_only_after_a_warning(menu, handler):
    handler(lambda session: session.out.line("the-backup-passphrase"))
    run(menu, "app", "passphrase", **{"<application>": "shop"})

    menu.press("p", "n")
    assert "the-backup-passphrase" not in menu.printed
    assert menu.saw("stays in the scrollback")

    menu.press("p", "y")
    assert "the-backup-passphrase" in menu.printed
