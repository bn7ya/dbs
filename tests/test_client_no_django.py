"""The client runs on a machine with no Django project and no configured settings."""

import os
import subprocess
import sys

import pytest

from dbs.engine import create_backup
from tests.conftest import FAST_KDF
from tests.testapp.models import Author

PASS = "no-django-pass-phrase"


def bare_env():
    env = dict(os.environ)
    env.pop("DJANGO_SETTINGS_MODULE", None)
    env.pop("DBS_PASSPHRASE", None)
    env["PYTHONPATH"] = os.getcwd()
    return env


def run_bare(*argv, env=None):
    return subprocess.run(
        [sys.executable, "-m", "dbs.client", *argv],
        capture_output=True,
        text=True,
        env=env or bare_env(),
    )


def test_the_cli_runs_without_django_settings():
    result = run_bare("--help")
    assert result.returncode == 0, result.stderr
    assert "dbs-client" in result.stdout


def test_init_print_runs_without_django_settings():
    result = run_bare("init", "--print")
    assert result.returncode == 0, result.stderr
    assert "servers.production" in result.stdout


def test_importing_the_cli_configures_no_settings_and_loads_no_engine():
    snippet = (
        "import dbs.client.cli, django.conf, sys;"
        "assert django.conf.settings.configured is False;"
        "assert 'dbs.engine.backup' not in sys.modules;"
        "assert 'dbs.engine.restore' not in sys.modules;"
        "print('ok')"
    )
    result = subprocess.run(
        [sys.executable, "-c", snippet],
        capture_output=True,
        text=True,
        env=bare_env(),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


@pytest.mark.django_db
def test_validate_works_without_django_settings(tmp_path):
    Author.objects.create(name="Ada")
    path = tmp_path / "portable.dbs"
    path.write_bytes(create_backup(PASS, kdf_params=FAST_KDF))

    structural = run_bare("validate", str(path), "--structure-only")
    assert structural.returncode == 0, structural.stderr
    assert "VALID" in structural.stdout

    env = bare_env()
    env["DBS_PASSPHRASE"] = PASS
    decrypted = run_bare("validate", str(path), env=env)
    assert decrypted.returncode == 0, decrypted.stderr
    assert "Decryption + payload hash: OK" in decrypted.stdout
