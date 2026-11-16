"""A server move between two real machines over OpenSSH: the old server and a bare new one."""

from __future__ import annotations

import os
import secrets
import shlex
from dataclasses import dataclass
from pathlib import Path

import pytest

import dbs
from dbs import audit
from dbs.manager.applications.repositories import ApplicationRepository
from dbs.manager.applications.services import ApplicationService, DiscoveryService
from dbs.manager.relocation.services import RelocationService
from dbs.manager.servers.services import ServerService
from dbs.manager.servers.services.server_service import fetch_host_key
from dbs.models import AuditEvent
from dbs.transports import SSHTarget, open_session
from tests.manager.support import PASSWORD

TITLES = ["carried", "across", "two machines"]
PYTHON_PACKAGE = "python3-venv"


@dataclass(frozen=True)
class Machine:
    host: str
    port: int
    user: str
    key: str
    known_hosts: str

    @property
    def named(self) -> bool:
        return bool(self.host and self.user and self.key and self.known_hosts)

    def run(self, command: str, timeout: float = 300):
        target = SSHTarget(
            host=self.host,
            port=self.port,
            username=self.user,
            key_filename=self.key,
            known_hosts=self.known_hosts,
            use_agent=False,
        )
        with open_session(target) as session:
            return session.run(command, timeout=timeout)

    def read(self, command: str) -> str:
        found = self.run(command)
        assert found.ok, found.stderr
        return found.stdout

    def has(self, path: str) -> bool:
        return self.read(f"test -e {shlex.quote(path)} && echo there || echo absent").strip() == "there"


def machine(prefix: str) -> Machine:
    return Machine(
        host=os.environ.get(f"{prefix}HOST", ""),
        port=int(os.environ.get(f"{prefix}PORT", "22")),
        user=os.environ.get(f"{prefix}USER", ""),
        key=os.environ.get(f"{prefix}KEY", ""),
        known_hosts=os.environ.get(f"{prefix}KNOWN_HOSTS", ""),
    )


OLD = machine("DBS_TEST_SSH_")
NEW = machine("DBS_TEST_MOVE_TARGET_")
PROJECT = os.environ.get("DBS_TEST_MOVE_PROJECT", "")
SUDO_PASSWORD = os.environ.get("DBS_TEST_MOVE_SUDO_PASSWORD", "")

CONFIGURED = bool(OLD.named and NEW.named and PROJECT)
SETUP = (
    "python scripts/vm_fixture.py move boots an old and a bare new guest and prints "
    "DBS_TEST_SSH_*, DBS_TEST_MOVE_TARGET_*, DBS_TEST_MOVE_PROJECT and "
    "DBS_TEST_MOVE_SUDO_PASSWORD."
)

if os.environ.get("DBS_TEST_MOVE_REQUIRED") and not (CONFIGURED and SUDO_PASSWORD):
    pytest.fail(f"DBS_TEST_MOVE_REQUIRED is set. {SETUP}", pytrace=False)

pytestmark = [
    pytest.mark.skipif(not CONFIGURED, reason=SETUP),
    pytest.mark.django_db(transaction=True),
]


def in_project(server: Machine, python: str, folder: str, code: str) -> str:
    script = f"import django; django.setup(); {code}"
    return server.read(
        f"cd {shlex.quote(folder)} && DJANGO_SETTINGS_MODULE=shop.settings "
        f"{shlex.quote(python)} -c {shlex.quote(script)}"
    ).strip()


def titles(server: Machine, python: str, folder: str) -> list[str]:
    printed = in_project(
        server,
        python,
        folder,
        "from notes.models import Note; "
        "print('|'.join(Note.objects.order_by('pk').values_list('title', flat=True)))",
    )
    return [title for title in printed.split("|") if title]


def migrations(server: Machine, python: str, folder: str) -> str:
    return server.read(
        f"cd {shlex.quote(folder)} && {shlex.quote(python)} manage.py showmigrations --plan"
    )


def digest_of(server: Machine, path: str) -> str:
    return server.read(f"sha256sum {shlex.quote(path)}").split()[0]


def finished(job) -> AuditEvent:
    return AuditEvent.objects.get(pk=job.pk)


def registered(admin, name: str, server: Machine):
    return ServerService(admin).create(
        name=name,
        host=server.host,
        port=server.port,
        username=server.user,
        auth_method="key",
        private_key=Path(server.key).read_text(encoding="utf-8"),
        host_key=fetch_host_key(server.host, server.port).line,
    )


@pytest.fixture
def servers(admin):
    return registered(admin, "old", OLD), registered(admin, "new", NEW)


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
def rows(application):
    in_project(
        OLD,
        application.python_path,
        PROJECT,
        "from notes.models import Note; Note.objects.all().delete(); "
        f"[Note.objects.create(title=title) for title in {TITLES!r}]",
    )
    return TITLES


@pytest.fixture
def folder():
    home = NEW.read('printf %s "$HOME"')
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


def test_the_two_servers_are_different_machines():
    assert OLD.read("cat /etc/machine-id") != NEW.read("cat /etc/machine-id")
    assert OLD.has(PROJECT)
    assert not NEW.has(PROJECT)


def test_a_rehearsal_plans_the_move_and_leaves_both_servers_alone(admin, servers, application, folder):
    before = digest_of(OLD, f"{PROJECT}/.env")

    job = moved(admin, servers, application, folder)

    assert job.status == audit.SUCCEEDED, (
        job.error_code,
        job.data.get("failed_step"),
        job.data.get("blockers"),
    )
    inventory = job.data["inventory"]
    assert "same_machine" not in {note["code"] for note in inventory["notes"]}
    [plan] = inventory["applications"]
    assert (plan["target_name"], plan["folder"]["target"]) == ("shop (new)", folder)
    assert not NEW.has(folder)
    assert ApplicationRepository().active().filter(server=servers[1]).count() == 0
    assert digest_of(OLD, f"{PROJECT}/.env") == before


@pytest.mark.skipif(not SUDO_PASSWORD, reason="DBS_TEST_MOVE_SUDO_PASSWORD names the SSH user's sudo password.")
def test_a_real_move_brings_the_rows_and_the_migrations_to_the_new_machine_and_leaves_the_old_one(
    admin, servers, application, rows, folder
):
    old_migrations = migrations(OLD, application.python_path, PROJECT)
    old_env = digest_of(OLD, f"{PROJECT}/.env")

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

    assert job.status == audit.SUCCEEDED, (
        job.error_code,
        job.data.get("failed_step"),
        job.data.get("output"),
    )
    [created] = job.data["created_applications"]
    target = ApplicationRepository().get(created["target"])
    assert (target.server_id, target.project_dir) == (servers[1].pk, folder)
    assert target.python_path.startswith(f"{folder}/")
    quoted = shlex.quote(folder)

    assert titles(NEW, target.python_path, folder) == rows
    assert migrations(NEW, target.python_path, folder) == old_migrations
    assert "[ ]" not in old_migrations
    assert NEW.run(f"cd {quoted} && {shlex.quote(target.python_path)} manage.py migrate --check").ok
    assert NEW.read(f"stat -c %U {quoted}").strip() == NEW.user
    carried_env = NEW.read(f"cat {quoted}/.env")
    assert PROJECT not in carried_env
    assert folder in carried_env
    assert NEW.read(f"dpkg-query -W -f '${{Status}}' {PYTHON_PACKAGE}").endswith("installed")

    ApplicationService(admin).check(target.pk)
    checked = ApplicationService(admin).get(target.pk)
    assert checked.last_check_status == "ok", repr(checked.last_check_report)
    assert checked.last_check_report["dbs_version"] == dbs.__version__

    assert titles(OLD, application.python_path, PROJECT) == rows
    assert migrations(OLD, application.python_path, PROJECT) == old_migrations
    assert digest_of(OLD, f"{PROJECT}/.env") == old_env
    assert ApplicationRepository().get(application.pk).server_id == servers[0].pk
    restores = AuditEvent.objects.filter(action="relocation.restore", status=audit.SUCCEEDED)
    assert restores.count() == 1
