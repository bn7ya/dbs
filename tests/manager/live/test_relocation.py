"""A server move over a real OpenSSH server, onto a second record of the same machine."""

from __future__ import annotations

import os
import secrets
import shlex
from pathlib import Path

import pytest

from dbs import audit
from dbs.manager.applications.repositories import ApplicationRepository
from dbs.manager.applications.services import ApplicationService, DiscoveryService
from dbs.manager.relocation.services import RelocationService
from dbs.manager.servers.services import ServerService
from dbs.manager.servers.services.server_service import fetch_host_key
from dbs.models import AuditEvent
from dbs.transports import SSHTarget, open_session
from tests.manager.support import PASSWORD

HOST = os.environ.get("DBS_TEST_SSH_HOST", "")
PORT = int(os.environ.get("DBS_TEST_SSH_PORT", "22"))
USER = os.environ.get("DBS_TEST_SSH_USER", "")
KEY = os.environ.get("DBS_TEST_SSH_KEY", "")
KNOWN_HOSTS = os.environ.get("DBS_TEST_SSH_KNOWN_HOSTS", "")
PROJECT = os.environ.get("DBS_TEST_MOVE_PROJECT", "")
SUDO_PASSWORD = os.environ.get("DBS_TEST_MOVE_SUDO_PASSWORD", "")

CONFIGURED = bool(HOST and USER and KEY and KNOWN_HOSTS and PROJECT)
SETUP = (
    "Start scripts/openssh_test_server.sh and scripts/e2e_fixture.sh, then set DBS_TEST_SSH_* "
    "and DBS_TEST_MOVE_PROJECT to a host project such as /srv/e2e/app; "
    "DBS_TEST_MOVE_SUDO_PASSWORD also moves it for real."
)

pytestmark = [
    pytest.mark.skipif(not CONFIGURED, reason=SETUP),
    pytest.mark.django_db(transaction=True),
]


def on_server(command: str) -> str:
    target = SSHTarget(
        host=HOST,
        port=PORT,
        username=USER,
        key_filename=KEY,
        known_hosts=KNOWN_HOSTS,
        use_agent=False,
    )
    with open_session(target) as session:
        found = session.run(command, timeout=120)
    assert found.ok, found.stderr
    return found.stdout


def finished(job) -> AuditEvent:
    return AuditEvent.objects.get(pk=job.pk)


def made(admin, name):
    return ServerService(admin).create(
        name=name,
        host=HOST,
        port=PORT,
        username=USER,
        auth_method="key",
        private_key=Path(KEY).read_text(encoding="utf-8"),
        host_key=fetch_host_key(HOST, PORT).line,
    )


@pytest.fixture
def servers(admin):
    return made(admin, "old"), made(admin, "new")


@pytest.fixture
def application(admin, servers):
    found = DiscoveryService(admin).discover(servers[0].pk, PROJECT, account_password=PASSWORD)
    [host] = [candidate for candidate in found["candidates"] if candidate["kind"] == "host"]
    service = ApplicationService(admin)
    created = service.create(
        server=servers[0].pk,
        name="shop",
        account_password=PASSWORD,
        kind="host",
        project_dir=host["project_dir"],
        python_path=host["python_path"],
        manage_path=host["manage_path"],
        settings_module=host["settings_module"],
        remote_backup_dir=host["remote_backup_dir"],
        env_path=f"{PROJECT}/.env",
        env_location="host",
        discovered=True,
    )
    return service.capture_passphrase(created.pk)


@pytest.fixture
def folder():
    home = on_server('printf %s "$HOME"')
    return f"{home}/moved-{secrets.token_hex(4)}"


def moved(admin, servers, application, folder, **real):
    return finished(
        RelocationService(admin).start(
            source_server=servers[0].pk,
            target_server=servers[1].pk,
            applications=[{"application": application.pk, "folder": folder}],
            **real,
        )
    )


def test_a_rehearsal_plans_the_move_and_leaves_both_servers_alone(admin, servers, application, folder):
    job = moved(admin, servers, application, folder)

    assert job.status == audit.SUCCEEDED, (job.error_code, job.data.get("blockers"))
    inventory = job.data["inventory"]
    assert {note["code"] for note in inventory["notes"]} >= {"same_machine"}
    [plan] = inventory["applications"]
    assert (plan["target_name"], plan["folder"]["target"]) == ("shop (new)", folder)
    assert plan["blockers"] == []
    assert on_server(f"test -e {shlex.quote(folder)} && echo there || echo absent").strip() == "absent"
    assert ApplicationRepository().active().filter(server=servers[1]).count() == 0


@pytest.mark.skipif(not SUDO_PASSWORD, reason="DBS_TEST_MOVE_SUDO_PASSWORD names the SSH user's sudo password.")
def test_a_real_move_runs_the_application_from_its_new_folder_and_its_own_database(
    admin, servers, application, folder
):
    job = moved(
        admin,
        servers,
        application,
        folder,
        rehearsal=False,
        password=PASSWORD,
        confirm_name="new",
        sudo_password=SUDO_PASSWORD,
    )

    assert job.status == audit.SUCCEEDED, (job.error_code, job.data.get("output"))
    [created] = job.data["created_applications"]
    target = ApplicationRepository().get(created["target"])
    assert (target.server_id, target.project_dir) == (servers[1].pk, folder)
    quoted = shlex.quote(folder)
    assert on_server(f"stat -c %U {quoted}").strip() == USER
    assert PROJECT not in on_server(f"cat {quoted}/.env")
    restores = AuditEvent.objects.filter(action="relocation.restore", status=audit.SUCCEEDED)
    assert restores.count() == 1
