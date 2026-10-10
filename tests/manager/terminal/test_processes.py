import socket
import subprocess
import sys

import pytest

from dbs import audit, leases
from dbs.manager import processes
from dbs.manager.activity import job_leases
from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.activity.services import ActivityService
from tests.manager.servers.support import host_key_line, private_key_text
from tests.manager.test_cli import ROOT, clean_env
from tests.manager.test_export_import import python

PASSWORD = "correct-horse-battery-staple"
TIMEOUT = 120

SEED = """
import sys
import django
from django.core.management import call_command

django.setup()
call_command("migrate", verbosity=0)
from uuid import uuid4
from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.backups.locks import TakeLock
from dbs.manager.servers.services import ServerService

user = UserRepository().create_superuser(username="sara", password=sys.argv[1])
server = ServerService(user).create(
    name="web-1", host="10.0.0.5", username="deploy", auth_method="key",
    private_key=sys.argv[2], host_key=sys.argv[3], backup_passphrase="a-passphrase",
)
assert TakeLock().acquire(server.pk, uuid4())
"""


def running_job(admin):
    queued = ActivityService(admin).queue("backup.take", target="web-1")
    return ActivityService(None).start(queued.pk)


@pytest.mark.django_db
def test_starting_the_manager_spares_a_job_a_live_process_is_running(admin):
    job = running_job(admin)

    ActivityService(None).interrupt()

    assert ActivityRepository().get(job.pk).status == audit.RUNNING


@pytest.mark.django_db
def test_starting_the_manager_fails_a_job_whose_process_is_gone(admin, monkeypatch):
    job = running_job(admin)
    leases.release(f"{job_leases.PREFIX}{job.pk}", leases.process_owner())
    leases.acquire(f"{job_leases.PREFIX}{job.pk}", f"{socket.gethostname()}:4242", 3600)
    monkeypatch.setattr(processes, "pid_running", lambda pid: False)

    ActivityService(None).interrupt()

    entry = ActivityRepository().get(job.pk)
    assert (entry.status, entry.error_code) == (audit.FAILED, "interrupted")


@pytest.mark.django_db
def test_a_finished_job_lets_go_of_its_lease(admin):
    job = running_job(admin)

    ActivityService(None).succeed(job.pk, {})

    assert job_leases.live() == []


def test_a_take_from_the_terminal_waits_for_one_the_manager_is_running(tmp_path):
    home = tmp_path / "home"
    python(SEED, home, PASSWORD, private_key_text(), host_key_line())

    ran = subprocess.run(
        [sys.executable, "-m", "dbs.manager", "backup", "take", "web-1"],
        cwd=ROOT,
        env=clean_env(DBS_MANAGER_HOME=str(home)),
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )

    assert ran.returncode == 1, ran.stderr
    assert "failed" in ran.stdout and "already" in ran.stdout.lower()


def test_help_for_the_terminal_commands_needs_no_django():
    script = (
        "import sys\n"
        "from dbs.manager import cli\n"
        "try:\n"
        "    cli.main(['server', 'add', '--help'])\n"
        "except SystemExit as stop:\n"
        "    assert stop.code == 0\n"
        "loaded = [name for name in sys.modules if name.startswith(('rest_framework', "
        "'django.db', 'dbs.manager.terminal.session'))]\n"
        "print(loaded)\n"
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
    assert "--host-key" in ran.stdout
    assert ran.stdout.strip().splitlines()[-1] == "[]"
