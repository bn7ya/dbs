"""DBS installs and runs in a project that has no django.contrib.admin."""

import os
import subprocess
import sys

SETTINGS = "tests.noadmin.settings"


def run(*argv):
    env = dict(os.environ)
    env["DJANGO_SETTINGS_MODULE"] = SETTINGS
    env["PYTHONPATH"] = os.getcwd()
    env.pop("DBS_PASSPHRASE", None)
    return subprocess.run(
        [sys.executable, "-c", _DRIVER, *argv],
        capture_output=True,
        text=True,
        env=env,
    )


_DRIVER = """
import sys
import django
from django.core.management import call_command

django.setup()
call_command("migrate", run_syncdb=True, verbosity=0)
call_command(*sys.argv[1:])
"""


def test_the_umbrella_command_runs_without_the_admin():
    result = run("dbs")

    assert result.returncode == 0, result.stderr
    assert "manage.py dbs backup" in result.stdout


def test_a_backup_round_trip_runs_without_the_admin(tmp_path):
    output = tmp_path / "no-admin.dbs"

    written = run("dbs", "backup", str(output), "--kdf-time", "1", "--kdf-memory", "8192")
    assert written.returncode == 0, written.stderr
    assert output.is_file()

    checked = run("dbs", "validate", str(output), "--passphrase")
    assert checked.returncode == 0, checked.stderr
    assert "VALID" in checked.stdout


def test_the_security_command_runs_without_the_admin():
    result = run("dbs", "security", "status")

    assert result.returncode == 0, result.stderr
    assert "log out at" in result.stdout


def test_the_guard_middleware_is_inert_without_admin_urls():
    result = run("dbs", "key")

    assert result.returncode == 0, result.stderr
    assert "SECRET_KEY" in result.stdout
