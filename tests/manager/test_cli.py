import json
import os
import queue
import re
import signal
import socket
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from dbs.manager import cli, paths, processes

ROOT = Path(__file__).resolve().parents[2]
URL = re.compile(r"running at (http://\S+)")
BOOT_SECONDS = 60


def clean_env(**extra):
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("DBS_MANAGER_") and key != "DJANGO_SETTINGS_MODULE"
    }
    env["DBS_MANAGER_KEY_STORE"] = "file"
    env.update(extra)
    return env


def manager(*args, **kwargs):
    return [sys.executable, "-m", "dbs.manager.cli", *args]


def fetch(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


class Running:
    def __init__(self, data_dir, *extra):
        self.lines = queue.Queue()
        self.process = subprocess.Popen(
            manager(
                "run",
                "--no-browser",
                "--port",
                "0",
                "--data-dir",
                str(data_dir),
                *extra,
            ),
            cwd=ROOT,
            env=clean_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        threading.Thread(target=self._read, daemon=True).start()
        self.url = self._wait_for_url()

    def _read(self):
        for line in self.process.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def _wait_for_url(self):
        seen = []
        while True:
            try:
                line = self.lines.get(timeout=BOOT_SECONDS)
            except queue.Empty:
                break
            if line is None:
                break
            seen.append(line)
            found = URL.search(line)
            if found:
                return found.group(1)
        self.process.kill()
        raise AssertionError("the manager did not start:\n" + "".join(seen))

    @property
    def base(self):
        return re.match(r"http://[^/]+", self.url).group(0)

    def stop(self):
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGTERM)
        return self.process.wait(timeout=30)


@pytest.mark.parametrize(
    ("platform", "environ", "expected"),
    [
        ("linux", {}, "/home/ada/.local/share/django-dbs"),
        ("linux", {"XDG_DATA_HOME": "/data"}, "/data/django-dbs"),
        ("darwin", {}, "/home/ada/Library/Application Support/django-dbs"),
        ("win32", {"LOCALAPPDATA": "/appdata"}, "/appdata/django-dbs"),
        ("win32", {}, "/home/ada/AppData/Local/django-dbs"),
    ],
)
def test_the_default_data_dir_follows_the_platform(platform, environ, expected):
    found = paths.resolve_data_dir(environ=environ, platform=platform, home="/home/ada")

    assert found == Path(expected)


def test_an_explicit_data_dir_beats_the_environment(tmp_path):
    environ = {paths.HOME_ENV: str(tmp_path / "from-env")}

    assert paths.resolve_data_dir(environ=environ) == tmp_path / "from-env"
    assert (
        paths.resolve_data_dir(str(tmp_path / "given"), environ=environ)
        == tmp_path / "given"
    )


def test_the_data_dir_is_private(tmp_path):
    home = paths.ensure_data_dir(tmp_path / "home")

    assert home.stat().st_mode & 0o777 == 0o700
    assert (home / "keys").stat().st_mode & 0o777 == 0o700


def test_the_key_is_created_once_and_readable_by_the_owner_alone(tmp_path):
    home = paths.ensure_data_dir(tmp_path / "home")

    first = paths.read_key(home)
    again = paths.read_key(home)

    assert first == again and len(first) >= 50
    assert paths.key_path(home).stat().st_mode & 0o777 == 0o600


def test_version_and_help_need_no_django(capsys):
    with pytest.raises(SystemExit) as stopped:
        cli.main(["--version"])

    assert stopped.value.code == 0
    assert capsys.readouterr().out.startswith("django_dbs ")
    assert cli.main([]) == 2


def test_python_dash_m_runs_the_manager_without_the_script_on_path():
    from dbs import __version__

    result = subprocess.run(
        [sys.executable, "-m", "dbs.manager", "--version"],
        cwd=ROOT,
        env=clean_env(),
        capture_output=True,
        text=True,
        timeout=BOOT_SECONDS,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"django_dbs {__version__}"


def test_without_the_manager_extra_one_line_names_the_install(monkeypatch, capsys):
    from dbs import extras

    real = extras.importable
    monkeypatch.setattr(extras, "importable", lambda name: name != "waitress" and real(name))

    assert cli.main(["run", "--no-browser"]) == 1

    printed = capsys.readouterr()
    assert printed.out == ""
    assert printed.err.splitlines() == [
        "django_dbs: the DBS manager needs waitress, which this environment lacks; "
        'install them with pip install "django-dbs[manager]"'
    ]


@pytest.mark.parametrize("entry", ["dbs.manager", "dbs.manager.cli"])
def test_python_dash_m_without_the_manager_extra_exits_without_a_traceback(entry):
    script = (
        "import runpy, sys\n"
        "sys.modules['rest_framework'] = None\n"
        "sys.argv = ['django_dbs', 'run', '--no-browser']\n"
        f"runpy.run_module({entry!r}, run_name='__main__', alter_sys=True)\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=clean_env(),
        capture_output=True,
        text=True,
        timeout=BOOT_SECONDS,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert len(result.stderr.splitlines()) == 1
    assert "rest_framework" in result.stderr
    assert 'pip install "django-dbs[manager]"' in result.stderr


def test_paths_names_every_file(tmp_path, capsys):
    assert cli.main(["paths", "--data-dir", str(tmp_path / "home")]) == 0

    out = capsys.readouterr().out
    assert str(tmp_path / "home") in out
    assert "manager.sqlite3" in out and "secret.key" in out and "manager.log" in out


@pytest.mark.parametrize("host", ["0.0.0.0", "192.0.2.10", "::"])
def test_listening_beyond_this_machine_is_refused_without_a_proxy(host):
    with pytest.raises(cli.CommandFailed) as refused:
        cli.exposure(host, [], insecure=False)

    assert "--trusted-proxy" in str(refused.value)
    assert "--allow-insecure-http" in str(refused.value)


def test_listening_beyond_this_machine_behind_a_proxy_is_allowed(capsys):
    cli.exposure("0.0.0.0", ["10.0.0.0/24"], insecure=False)

    assert "behind the proxy at 10.0.0.0/24" in capsys.readouterr().err


def test_plain_http_beyond_this_machine_needs_asking_for_and_warns(capsys):
    cli.exposure("192.0.2.10", [], insecure=True)

    assert capsys.readouterr().err.startswith("WARNING: listening on 192.0.2.10")


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_listening_on_this_machine_alone_is_quiet(host, capsys):
    cli.exposure(host, [], insecure=False)

    assert capsys.readouterr().err == ""


def test_a_trusted_proxy_is_an_address_range():
    assert cli.trusted_proxies(["10.0.0.7/24,fd00::1"]) == [
        "10.0.0.0/24",
        "fd00::1/128",
    ]
    with pytest.raises(cli.CommandFailed):
        cli.trusted_proxies(["proxy.example.com"])


def test_run_refuses_to_listen_beyond_this_machine_without_a_proxy(tmp_path):
    refused = subprocess.run(
        manager(
            "run", "--no-browser", "--host", "0.0.0.0", "--data-dir", str(tmp_path)
        ),
        cwd=ROOT,
        env=clean_env(),
        capture_output=True,
        text=True,
        timeout=BOOT_SECONDS,
    )

    assert refused.returncode == 1
    assert "--trusted-proxy" in refused.stderr
    assert not (tmp_path / "manager.sqlite3").exists()


def test_the_browser_is_sent_to_a_reachable_address():
    assert cli.browser_host("0.0.0.0") == "127.0.0.1"
    assert cli.browser_host("::1") == "[::1]"
    assert cli.browser_host("127.0.0.1") == "127.0.0.1"


def test_a_lease_left_by_a_dead_process_on_this_host_is_abandoned(monkeypatch):
    monkeypatch.setattr(processes, "pid_running", lambda pid: False)
    host = socket.gethostname()

    assert processes.abandoned(f"{host}:4242")
    assert not processes.abandoned("another-host:4242")
    assert not processes.abandoned(f"{host}:{os.getpid()}")


def test_run_boots_answers_and_refuses_a_second_instance(tmp_path):
    home = tmp_path / "home"
    first = Running(home)
    try:
        assert "/setup?token=" in first.url
        token = first.url.rsplit("token=", 1)[1]
        assert (home / "setup.token").read_text() == token

        status, body = fetch(f"{first.base}/api/health/")
        assert status == 200 and json.loads(body)["status"] == "ok"
        assert fetch(f"{first.base}/")[0] == 200
        assert fetch(f"{first.base}/api/setup/") == (200, b'{"needed":true}')
        assert fetch(f"{first.base}/api/nope/")[0] == 404

        instance = json.loads((home / "manager.json").read_text())
        assert instance["pid"] == first.process.pid
        assert instance["url"] == f"{first.base}/"

        second = subprocess.run(
            manager("run", "--no-browser", "--data-dir", str(home)),
            cwd=ROOT,
            env=clean_env(),
            capture_output=True,
            text=True,
            timeout=BOOT_SECONDS,
        )
        assert second.returncode == 0
        assert f"already running at {first.base}/" in second.stdout
    finally:
        assert first.stop() == 0

    assert not (home / "manager.json").exists()
    assert (home / "manager.sqlite3").exists()
    assert (home / "keys" / "secret.key").stat().st_mode & 0o777 == 0o600


def test_once_an_account_exists_run_opens_the_front_page(tmp_path):
    home = tmp_path / "home"
    created = subprocess.run(
        manager("createuser", "sara", "--password-stdin", "--data-dir", str(home)),
        cwd=ROOT,
        env=clean_env(),
        input="correct-horse-battery-staple\n",
        capture_output=True,
        text=True,
        timeout=BOOT_SECONDS,
    )
    assert created.returncode == 0, created.stderr

    running = Running(home)
    try:
        assert running.url == f"{running.base}/"
        assert not (home / "setup.token").exists()
    finally:
        running.stop()


def test_password_changes_an_accounts_password_and_refuses_an_unknown_one(tmp_path):
    home = str(tmp_path / "home")

    def command(*args, password="correct-horse-battery-staple"):
        return subprocess.run(
            manager(*args, "--password-stdin", "--data-dir", home),
            cwd=ROOT,
            env=clean_env(),
            input=f"{password}\n",
            capture_output=True,
            text=True,
            timeout=BOOT_SECONDS,
        )

    assert command("createuser", "sara").returncode == 0
    assert command("createuser", "sara", "--role", "admin").returncode == 1
    same = command("password", "sara")
    assert same.returncode == 1 and "has not been using" in same.stderr
    changed = command("password", "sara", password="another-long-passphrase")
    assert changed.returncode == 0, changed.stderr
    assert "Changed the password of sara" in changed.stdout
    unknown = command("password", "omar")
    assert unknown.returncode == 1
    assert "no account named 'omar'" in unknown.stderr


def test_createuser_refuses_a_weak_password(tmp_path):
    result = subprocess.run(
        manager(
            "createuser",
            "sara",
            "--password-stdin",
            "--data-dir",
            str(tmp_path / "home"),
        ),
        cwd=ROOT,
        env=clean_env(),
        input="123\n",
        capture_output=True,
        text=True,
        timeout=BOOT_SECONDS,
    )

    assert result.returncode == 1
    assert "too short" in result.stderr
