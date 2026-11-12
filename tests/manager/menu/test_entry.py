import subprocess
import sys

import pytest

from dbs.manager import cli
from dbs.manager.menu import entry
from tests.manager.test_cli import ROOT, clean_env

TIMEOUT = 60


class Stream:
    def __init__(self, terminal):
        self.terminal = terminal

    def isatty(self):
        return self.terminal


@pytest.fixture
def opened(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "setup_django", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "resolve", lambda args: None)
    monkeypatch.setattr(
        entry, "opened", lambda account=None: calls.append(account) or 0
    )
    return calls


@pytest.fixture
def on_a_terminal(monkeypatch):
    monkeypatch.setattr(cli, "menu_can_open", lambda: True)


def test_typed_alone_on_a_terminal_the_command_opens_the_menu(opened, on_a_terminal):
    assert cli.main([]) == 0
    assert opened == [None]


def test_typed_alone_without_a_terminal_it_prints_the_help_and_returns_2(
    opened, capsys
):
    assert cli.main([]) == 2
    assert opened == []
    printed = capsys.readouterr().out
    assert printed.startswith("usage: ") and "COMMAND" in printed


def test_the_menu_command_opens_it_as_the_account_named(opened, on_a_terminal):
    assert cli.main(["menu", "--as", "omar"]) == 0
    assert opened == ["omar"]


def test_the_menu_command_without_a_terminal_points_to_the_commands(opened, capsys):
    assert cli.main(["menu"]) == 1
    assert opened == []
    assert "needs a terminal" in capsys.readouterr().err


def test_a_refusal_while_opening_is_printed_like_any_other(
    monkeypatch, opened, on_a_terminal, capsys
):
    def refused(account=None):
        raise cli.CommandFailed("there is no account named 'nadia'.")

    monkeypatch.setattr(entry, "opened", refused)

    assert cli.main(["menu", "--as", "nadia"]) == 1
    assert "no account named 'nadia'" in capsys.readouterr().err


@pytest.mark.parametrize(
    "stdin, stdout, term, expected",
    [
        (True, True, "xterm-256color", True),
        (True, True, "linux", True),
        (False, True, "xterm-256color", False),
        (True, False, "xterm-256color", False),
        (True, True, "dumb", False),
        (True, True, "", False),
    ],
)
def test_the_menu_opens_only_where_a_person_can_use_it(
    monkeypatch, stdin, stdout, term, expected
):
    monkeypatch.setattr(entry.os, "name", "posix")

    assert entry.available({"TERM": term}, Stream(stdin), Stream(stdout)) is expected


@pytest.mark.parametrize("able", [True, False])
def test_on_windows_the_console_says_whether_it_can_show_the_menu(monkeypatch, able):
    from dbs.manager.menu.kit import terminal

    monkeypatch.setattr(entry.os, "name", "nt")
    monkeypatch.setattr(terminal, "capable", lambda: able)

    assert entry.available({}, Stream(True), Stream(True)) is able
    assert entry.available({}, Stream(False), Stream(True)) is False


def test_a_closed_stream_is_not_a_terminal():
    class Closed:
        def isatty(self):
            raise ValueError("I/O operation on closed file")

    assert entry.available({"TERM": "xterm"}, Closed(), Stream(True)) is False


def test_help_and_the_bare_command_in_a_pipe_load_no_django_and_no_screen():
    script = (
        "import sys\n"
        "from dbs.manager import cli\n"
        "try:\n"
        "    cli.main(['--help'])\n"
        "except SystemExit as stop:\n"
        "    assert stop.code == 0\n"
        "assert cli.main([]) == 2\n"
        "print([name for name in sys.modules if name.startswith(('rest_framework', "
        "'django.db', 'dbs.manager.menu.app', 'dbs.manager.menu.kit'))])\n"
    )
    ran = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=clean_env(),
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )

    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.strip().splitlines()[-1] == "[]"


def test_the_menu_is_listed_among_the_commands(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])

    assert "menu" in capsys.readouterr().out
