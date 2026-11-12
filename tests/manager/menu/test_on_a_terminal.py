import os
import select
import signal
import socket
import struct
import subprocess
import sys
import threading
import time

import paramiko
import pytest

from tests.manager.test_cli import ROOT, clean_env

pty = pytest.importorskip("pty")
fcntl = pytest.importorskip("fcntl")
termios = pytest.importorskip("termios")

TIMEOUT = 60
PASSWORD = "correct-horse-battery-staple"
ENTERED = "\x1b[?1049h"
LEFT = "\x1b[?1049l"
COLUMNS = 110
BETWEEN_KEYS = 0.4
ROWS = 34


def controlled_by_its_terminal():
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


class OnATerminal:
    def __init__(self, home):
        self.controller, follower = pty.openpty()
        fcntl.ioctl(
            follower, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLUMNS, 0, 0)
        )
        self.process = subprocess.Popen(
            [sys.executable, "-m", "dbs.manager"],
            cwd=ROOT,
            env=clean_env(
                DBS_MANAGER_HOME=str(home), TERM="xterm-256color", COLORTERM="truecolor"
            ),
            stdin=follower,
            stdout=follower,
            stderr=follower,
            start_new_session=True,
            preexec_fn=controlled_by_its_terminal,
        )
        os.close(follower)
        self.shown = ""

    def read(self, wait):
        ready, _, _ = select.select([self.controller], [], [], wait)
        if not ready:
            return False
        try:
            self.shown += os.read(self.controller, 65536).decode("utf-8", "replace")
        except OSError:
            return False
        return True

    def until(self, text):
        deadline = time.monotonic() + TIMEOUT
        while text not in self.shown:
            assert time.monotonic() < deadline, (
                f"never saw {text!r} in:\n{self.shown[-2000:]}"
            )
            self.read(0.2)

    def press(self, *typed):
        for keys in typed:
            os.write(self.controller, keys.encode())
            time.sleep(BETWEEN_KEYS)

    def ended(self):
        deadline = time.monotonic() + TIMEOUT
        while self.process.poll() is None and time.monotonic() < deadline:
            self.read(0.1)
        while self.read(0.2):
            continue
        return self.process.wait(timeout=TIMEOUT)

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait()
        os.close(self.controller)


@pytest.fixture
def terminal(tmp_path):
    opened = []

    def open_on(home=None):
        found = OnATerminal(home or tmp_path / "home")
        opened.append(found)
        return found

    yield open_on
    for found in opened:
        found.close()


@pytest.fixture
def home(tmp_path):
    folder = tmp_path / "home"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "dbs.manager",
            "createuser",
            "sara",
            "--password-stdin",
            "--data-dir",
            str(folder),
        ],
        cwd=ROOT,
        env=clean_env(),
        input=f"{PASSWORD}\n",
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
        check=True,
    )
    return folder


def test_typed_alone_it_takes_the_screen_and_q_gives_it_back(terminal, home):
    menu = terminal(home)

    menu.until("Dashboard")
    assert ENTERED in menu.shown and "sara" in menu.shown
    menu.press("q")

    assert menu.ended() == 0
    assert menu.shown.rstrip().endswith(LEFT)


def test_control_c_leaves_the_menu_like_q(terminal, home):
    menu = terminal(home)
    menu.until("Dashboard")

    menu.press("\x03")

    assert menu.ended() == 0
    assert LEFT in menu.shown


def test_the_arrow_keys_move_between_the_sections(terminal, home):
    menu = terminal(home)
    menu.until("Dashboard")

    menu.press("\x1b[B")
    menu.until("No servers yet. Add a server")
    menu.press(*["\x1b[B"] * 6)
    menu.until("Every command the manager has")
    menu.press("q")

    assert menu.ended() == 0


def test_a_new_installation_is_offered_its_first_account(terminal):
    menu = terminal()

    menu.until("The first account")
    menu.press("sara\r")
    menu.until("Password for sara")
    menu.press(PASSWORD, "\r", PASSWORD, "\r")
    menu.until("sara · master")
    menu.press("q")

    assert menu.ended() == 0
    assert PASSWORD not in menu.shown


def test_a_stop_signal_gives_the_screen_back_first(terminal, home):
    menu = terminal(home)
    menu.until("Dashboard")

    menu.process.send_signal(signal.SIGTERM)

    assert menu.ended() == 128 + signal.SIGTERM
    assert LEFT in menu.shown


SILENT_SERVER = """
import sys
from dbs.manager import cli

cli.setup_django(sys.argv[1])

from django.contrib.auth import get_user_model
from tests.manager.factories import make_server

make_server(get_user_model().objects.get(), name="web-1", host="127.0.0.1", port=int(sys.argv[2]))
"""


@pytest.fixture
def silent_server(home):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)
    subprocess.run(
        [
            sys.executable,
            "-c",
            SILENT_SERVER,
            str(home),
            str(listener.getsockname()[1]),
        ],
        cwd=ROOT,
        env=clean_env(),
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
        check=True,
    )
    yield listener
    listener.close()


def test_control_c_stops_a_running_command_and_the_menu_stays_open(
    terminal, home, silent_server
):
    menu = terminal(home)
    menu.until("Dashboard")
    menu.press("\x1b[B", "\r", "\r")
    menu.until("Check the connection")
    menu.press("\x1b[B", "\x1b[B", "\r")
    menu.until("Ctrl+C stops it.")

    menu.press("\x03")
    menu.until("Stopped.")
    assert menu.process.poll() is None

    menu.press("\r")
    menu.until("Browse its folders")
    menu.press("q")
    assert menu.ended() == 0


def test_a_larger_window_is_drawn_into_at_once(terminal, home):
    menu = terminal(home)
    menu.until("Dashboard")
    assert "\x1b[40;1H" not in menu.shown

    fcntl.ioctl(menu.controller, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 130, 0, 0))

    menu.until("\x1b[40;1H")
    menu.press("q")
    assert menu.ended() == 0


def test_control_z_gives_the_screen_back_and_takes_it_again_when_continued(
    terminal, home
):
    menu = terminal(home)
    menu.until("Dashboard")

    menu.press("\x1a")
    menu.until(LEFT)
    os.kill(menu.process.pid, signal.SIGCONT)
    deadline = time.monotonic() + TIMEOUT
    while menu.shown.count(ENTERED) < 2 and time.monotonic() < deadline:
        menu.read(0.2)

    assert menu.shown.count(ENTERED) == 2
    menu.press("q")
    assert menu.ended() == 0


SSH_PASSWORD = "the-ssh-password"


class SignsInWithAPassword(paramiko.ServerInterface):
    def __init__(self, offered):
        self.offered = offered

    def get_allowed_auths(self, username):
        return "password"

    def check_auth_password(self, username, password):
        self.offered.append(password)
        if password == SSH_PASSWORD:
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED

    def check_channel_exec_request(self, channel, command):
        threading.Thread(
            target=lambda: (channel.send_exit_status(1), channel.close()), daemon=True
        ).start()
        return True


@pytest.fixture
def ssh_server():
    offered = []
    host_key = paramiko.ECDSAKey.generate()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(20)

    def serve():
        while True:
            try:
                connection, _ = listener.accept()
            except OSError:
                return
            transport = paramiko.Transport(connection)
            transport.add_server_key(host_key)
            try:
                transport.start_server(server=SignsInWithAPassword(offered))
            except Exception:
                transport.close()

    threading.Thread(target=serve, daemon=True).start()
    yield listener.getsockname()[1], offered
    listener.close()


def test_a_server_is_added_with_its_ssh_password_typed_in_the_form(
    terminal, home, ssh_server
):
    port, offered = ssh_server
    menu = terminal(home)
    menu.until("Dashboard")
    menu.press("\x1b[B", "\r", "a")
    menu.until("SSH password")

    menu.press("web-1", "\x1b[B", "127.0.0.1", "\x1b[B", str(port), "\x1b[B", "deploy")
    menu.press("\x1b[B", "\x1b[B", SSH_PASSWORD, *["\x1b[B"] * 4, "\r")
    menu.until("Is this the server's key?")
    menu.press("y")
    menu.until("Added web-1.")

    assert offered == [SSH_PASSWORD]
    assert SSH_PASSWORD not in menu.shown
    menu.press("\r", "q")
    assert menu.ended() == 0
