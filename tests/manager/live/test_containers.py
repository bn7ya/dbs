"""The manager against a real Docker or Podman Compose project over a real OpenSSH server."""

from __future__ import annotations

import io
import os
import shlex
import time
from pathlib import Path

import pytest

import dbs
from dbs import audit, validate_backup
from dbs.manager.applications.services import ApplicationService, DiscoveryService
from dbs.manager.backups.models import BackupFile
from dbs.manager.backups.repositories import BackupFileRepository
from dbs.manager.backups.services import BackupService
from dbs.manager.backups.storage import BackupStorage
from dbs.manager.envfiles.services import EnvFileService
from dbs.manager.redeploy.services import RedeployService
from dbs.manager.servers.services import ServerService
from dbs.manager.servers.services.server_service import fetch_host_key
from dbs.manager.shell.service import ShellService, finish
from dbs.models import AuditEvent
from dbs.transports import SSHTarget, open_session
from tests.manager.support import PASSWORD

ENGINE = os.environ.get("DBS_TEST_CONTAINER_ENGINE", "")
FOLDER = os.environ.get("DBS_TEST_CONTAINER_FOLDER", "")
HOST = os.environ.get("DBS_TEST_SSH_HOST", "")
PORT = int(os.environ.get("DBS_TEST_SSH_PORT", "22"))
USER = os.environ.get("DBS_TEST_SSH_USER", "")
KEY = os.environ.get("DBS_TEST_SSH_KEY", "")
KNOWN_HOSTS = os.environ.get("DBS_TEST_SSH_KNOWN_HOSTS", "")
PASSPHRASE = "live-container-passphrase"
IMAGE = "localhost/dbs-live-shop"
VOLUME = "shop_data"

CONFIGURED = bool(ENGINE and FOLDER and HOST and USER and KEY and KNOWN_HOSTS)
SETUP = (
    "Start scripts/openssh_test_server.sh and scripts/container_fixture.sh, then set "
    "DBS_TEST_CONTAINER_ENGINE, DBS_TEST_CONTAINER_FOLDER and DBS_TEST_SSH_*."
)

if os.environ.get("DBS_TEST_CONTAINER_REQUIRED") and not CONFIGURED:
    pytest.fail(f"DBS_TEST_CONTAINER_REQUIRED is set. {SETUP}", pytrace=False)

pytestmark = [
    pytest.mark.skipif(not CONFIGURED, reason=SETUP),
    pytest.mark.django_db(transaction=True),
]


def on_server(command: str, *, stdin_line: str | None = None, timeout: float = 300):
    target = SSHTarget(
        host=HOST,
        port=PORT,
        username=USER,
        key_filename=KEY,
        known_hosts=KNOWN_HOSTS,
        use_agent=False,
    )
    with open_session(target) as session:
        return session.run(
            f"cd {shlex.quote(FOLDER)} && {command}",
            stdin_line=stdin_line,
            timeout=timeout,
        )


def in_application(python: str) -> str:
    code = f"import django; django.setup(); {python}"
    found = on_server(f"{ENGINE} compose exec -T web python -c {shlex.quote(code)}")
    assert found.ok, found.stderr
    return found.stdout.strip()


def notes() -> list[str]:
    printed = in_application(
        "from notes.models import Note; "
        "print(','.join(Note.objects.order_by('pk').values_list('title', flat=True)))"
    )
    return [title for title in printed.split(",") if title]


@pytest.fixture
def server(admin):
    return ServerService(admin).create(
        name="live",
        host=HOST,
        port=PORT,
        username=USER,
        auth_method="key",
        private_key=Path(KEY).read_text(encoding="utf-8"),
        host_key=fetch_host_key(HOST, PORT).line,
    )


@pytest.fixture
def candidate(admin, server):
    found = DiscoveryService(admin).discover(server.pk, FOLDER, account_password=PASSWORD)
    composed = [
        candidate for candidate in found["candidates"] if candidate["kind"] == "compose"
    ]
    assert composed, found
    return composed[0]


@pytest.fixture
def application(admin, server, candidate):
    env = candidate["env"][0]
    created = ApplicationService(admin).create(
        server=server.pk,
        name="shop",
        account_password=PASSWORD,
        kind=candidate["kind"],
        engine=candidate["engine"],
        compose_project=candidate["compose_project"],
        compose_service=candidate["compose_service"],
        compose_files=candidate["compose_files"],
        project_dir=candidate["project_dir"],
        workdir=candidate["workdir"],
        python_path=candidate["python_path"],
        manage_path=candidate["manage_path"],
        settings_module=candidate["settings_module"],
        remote_backup_dir=candidate["remote_backup_dir"],
        env_path=env["path"],
        env_location=env["location"],
        backup_passphrase=PASSPHRASE,
        discovered=True,
    )
    ApplicationService(admin).check(created.pk)
    in_application("from notes.models import Note; Note.objects.all().delete()")
    return ApplicationService(admin).get(created.pk)


def finished(job) -> AuditEvent:
    return AuditEvent.objects.get(pk=job.pk)


def taken(admin, application) -> BackupFile:
    job = finished(BackupService(admin).take(application.pk))
    assert job.status == audit.SUCCEEDED, job.data
    return BackupFileRepository().get(job.data["backup"])


def test_discovery_finds_the_compose_service_and_where_its_paths_are_on_the_host(
    candidate,
):
    assert (candidate["engine"], candidate["compose_service"]) == (ENGINE, "web")
    assert candidate["compose_project"] == "shop"
    assert candidate["running"] is True
    assert candidate["dbs_version"] == dbs.__version__
    assert candidate["compatible"] is True
    assert candidate["settings_module"] == "shop.settings"
    assert candidate["remote_backup_dir"] == "/var/backups/dbs"
    assert candidate["backup_dir_on_host"] == f"{FOLDER}/backups"
    assert {"path": f"{FOLDER}/.env", "location": "host", "source": "compose"} in candidate[
        "env"
    ]
    assert candidate["problems"] == []


def test_a_discovered_application_checks_clean(application):
    report = application.last_check_report

    assert application.last_check_status == "ok", repr(report)
    assert report["dbs_version"] == dbs.__version__
    assert report["backup_command"] is True
    assert report["remote_backup_dir"] is True
    assert report["env_file"] is True


def test_a_backup_arrives_verified_and_leaves_nothing_in_the_container(
    admin, application
):
    in_application("from notes.models import Note; Note.objects.create(title='kept')")

    backup = taken(admin, application)

    assert backup.validation == BackupFile.Validation.VERIFIED
    with BackupStorage().open_read(backup.storage_path) as handle:
        assert validate_backup(handle, PASSPHRASE).ok
    in_folder = on_server(f"{ENGINE} compose exec -T web ls -A /var/backups/dbs")
    assert in_folder.ok, in_folder.stderr
    assert in_folder.stdout.strip() == ""
    leftovers = on_server(
        f"{ENGINE} compose exec -T web sh -c "
        "'ls -A /var/backups/dbs /tmp | grep -E \"part-|dbs-restore\" || true'"
    )
    assert leftovers.stdout.strip() == ""


def test_a_restore_is_rehearsed_then_brings_the_data_back(admin, application):
    in_application("from notes.models import Note; Note.objects.create(title='before')")
    backup = taken(admin, application)
    in_application(
        "from notes.models import Note; "
        "Note.objects.all().delete(); Note.objects.create(title='after')"
    )
    service = BackupService(admin)

    rehearsed = finished(service.restore(backup.pk, mode="replace", rehearse=True))
    assert rehearsed.status == audit.SUCCEEDED, rehearsed.data
    assert notes() == ["after"]

    restored = finished(
        service.restore(
            backup.pk,
            mode="replace",
            rehearse=False,
            account_password=PASSWORD,
            application_name="shop",
        )
    )
    assert restored.status == audit.SUCCEEDED, restored.data
    assert notes() == ["before"]


def test_the_env_file_beside_the_compose_project_is_kept_in_versions(
    admin, application
):
    pulled = EnvFileService(admin).pull(application.pk)

    assert pulled.created is True
    assert pulled.version.key_names == ["SHOP_SECRET_KEY"]


def test_a_deploy_restarts_the_service_and_migrates(admin, application):
    ApplicationService(admin).set_deploy_steps(
        application.pk,
        [{"kind": "restart"}, {"kind": "migrate"}],
        account_password=PASSWORD,
    )
    service = RedeployService(admin)

    rehearsed = finished(service.deploy(application.pk, rehearsal=True))
    deployed = finished(
        service.deploy(
            application.pk, rehearsal=False, password=PASSWORD, confirm_name="shop"
        )
    )

    assert rehearsed.status == audit.SUCCEEDED, rehearsed.data
    assert deployed.status == audit.SUCCEEDED, deployed.data
    assert [step["status"] for step in deployed.data["steps"]] == ["succeeded"] * 6
    assert deployed.data["before"].get("image")
    assert notes() == []


def test_a_terminal_runs_a_shell_inside_the_container(admin, application):
    session = ShellService(admin, "live").open(
        mode="application", application=application.pk, password=PASSWORD
    )
    try:
        assert session.write(0, b"echo $((6*7))-$(id -u)\r")
        seen, cursor, deadline = b"", 0, time.monotonic() + 30
        while b"42-10001" not in seen and time.monotonic() < deadline:
            data, cursor, _ = session.read(cursor, 1.0)
            seen += data
    finally:
        finish(session)

    assert b"42-10001" in seen
    entry = AuditEvent.objects.get(action="shell.session")
    assert b"echo" not in str(entry.data).encode()


def test_a_read_only_container_streams_a_backup_the_host_validates(tmp_path):
    command = (
        f"{ENGINE} run --rm -i --read-only --tmpfs /tmp --network none "
        f"-v {VOLUME}:/app/data {IMAGE} python manage.py dbs_backup --stream "
        "--passphrase-stdin --output-dir /tmp"
    )
    target = SSHTarget(
        host=HOST,
        port=PORT,
        username=USER,
        key_filename=KEY,
        known_hosts=KNOWN_HOSTS,
        use_agent=False,
    )
    received = io.BytesIO()
    with open_session(target) as session:
        result = session.stream(command, received, stdin_line=PASSPHRASE, timeout=300)

    assert result.ok, result.stderr
    path = tmp_path / "streamed.dbs"
    path.write_bytes(received.getvalue())
    assert validate_backup(path, PASSPHRASE).ok
