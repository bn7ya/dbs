from __future__ import annotations

import pytest

from dbs.manager.relocation import catalogue
from dbs.manager.relocation.exceptions import (
    PrivilegedCommandFailed,
    SudoMissing,
    SudoNeedsTty,
    SudoPasswordRequired,
    SudoPasswordWrong,
)
from dbs.manager.relocation.privileged import Privileged, SudoPasswords, sudo_mode
from dbs.manager.servers.gateways import RemoteHost
from tests.manager.remote import ScriptedSession

SECRET = "hunter2-sudo"


def remote_with(commands):
    session = ScriptedSession("10.0.0.9", commands)
    return RemoteHost(session), session


def test_the_sudo_passwords_never_show_in_a_repr():
    assert SECRET not in repr(SudoPasswords(target=SECRET, source=SECRET))


@pytest.mark.parametrize(
    ("commands", "mode"),
    [
        ({("id",): (0, "uid=0(root) gid=0(root)\n", "")}, catalogue.ROOT),
        ({("id",): (0, "uid=1000(deploy)\n", "")}, catalogue.MISSING),
        (
            {
                ("id",): (0, "uid=1000(deploy)\n", ""),
                ("sudo", "--version"): (0, "Sudo version 1.9\n", ""),
                ("sudo", "-n", "-k", "--", "true"): (0, "", ""),
            },
            catalogue.NOPASSWD,
        ),
        (
            {
                ("id",): (0, "uid=1000(deploy)\n", ""),
                ("sudo", "--version"): (0, "Sudo version 1.9\n", ""),
                ("sudo", "-n", "-k", "--", "true"): (1, "", "sudo: a password is required\n"),
            },
            catalogue.PASSWORD,
        ),
    ],
)
def test_how_root_is_reached(commands, mode):
    remote, session = remote_with(commands)

    assert sudo_mode(remote) == mode
    assert all(run["stdin"] is None for run in session.runs)


def test_the_password_goes_only_to_sudo_that_reads_it():
    remote, session = remote_with(
        {
            ("sudo", "-S", "-p", "", "-k", "--", "true"): (0, "", ""),
            ("sudo", "-S", "-p", "", "-k", "--", "env"): lambda argv, line: (0, "", ""),
            ("uname", "-m"): (0, "x86_64\n", ""),
        }
    )
    privileged = Privileged(remote, catalogue.PASSWORD, SECRET)

    privileged.run(catalogue.uname_machine())
    privileged.run(catalogue.apt_update())

    lines = {tuple(run["argv"][:2]): run["stdin"] for run in session.runs}
    assert lines[("uname", "-m")] is None
    assert lines[("sudo", "-S")] == SECRET
    assert [run["argv"][-1] for run in session.runs if run["argv"][0] == "sudo"] == [
        "true",
        "update",
    ]


def test_the_password_is_checked_once_per_run():
    remote, session = remote_with(
        {
            ("sudo", "-S", "-p", "", "-k", "--"): lambda argv, line: (0, "", ""),
        }
    )
    privileged = Privileged(remote, catalogue.PASSWORD, SECRET)

    privileged.run(catalogue.apt_update())
    privileged.run(catalogue.nginx_test())

    assert [run["argv"][-1] for run in session.runs].count("true") == 1


def test_without_a_password_nopasswd_sends_no_line():
    remote, session = remote_with(
        {("sudo", "-n", "-k", "--"): lambda argv, line: (0, "", "")}
    )

    Privileged(remote, catalogue.NOPASSWD).run(catalogue.apt_update())

    assert [run["stdin"] for run in session.runs] == [None]


@pytest.mark.parametrize(
    ("stderr", "raised"),
    [
        ("sudo: 1 incorrect password attempt\n", SudoPasswordWrong),
        ("Sorry, try again.\n", SudoPasswordWrong),
        ("sudo: sorry, you must have a tty to run sudo\n", SudoNeedsTty),
    ],
)
def test_sudo_refusals_are_named(stderr, raised):
    remote, _ = remote_with({("sudo", "-S", "-p", "", "-k", "--", "true"): (1, "", stderr)})

    with pytest.raises(raised):
        Privileged(remote, catalogue.PASSWORD, SECRET).run(catalogue.apt_update())


def test_a_password_mode_without_a_password_asks_for_one():
    remote, session = remote_with({})

    with pytest.raises(SudoPasswordRequired):
        Privileged(remote, catalogue.PASSWORD, "").run(catalogue.apt_update())
    assert session.runs == []


def test_without_sudo_root_commands_never_run():
    remote, session = remote_with({})

    with pytest.raises(SudoMissing):
        Privileged(remote, catalogue.MISSING).run(catalogue.apt_update())
    assert session.runs == []


def test_a_failed_command_never_shows_the_password():
    remote, _ = remote_with(
        {
            ("sudo", "-S", "-p", "", "-k", "--", "true"): (0, "", ""),
            ("sudo", "-S", "-p", "", "-k", "--", "env"): lambda argv, line: (
                100,
                "",
                f"E: could not open lock; echo {SECRET}\n",
            ),
        }
    )

    with pytest.raises(PrivilegedCommandFailed) as failed:
        Privileged(remote, catalogue.PASSWORD, SECRET).run(catalogue.apt_update())

    assert SECRET not in failed.value.output
    assert "***" in failed.value.output


def test_a_feed_through_sudo_sends_the_password_line_then_the_data():
    remote, session = remote_with(
        {
            ("sudo", "-S", "-p", "", "-k", "--", "true"): (0, "", ""),
            ("feed", "sudo", "-S"): lambda argv, line, data: (0, "", ""),
        }
    )

    Privileged(remote, catalogue.PASSWORD, SECRET).feed(catalogue.mysql_shell(), b"SELECT 1;\n")

    [fed] = session.feeds
    assert fed["stdin"] == SECRET and fed["data"] == b"SELECT 1;\n"
