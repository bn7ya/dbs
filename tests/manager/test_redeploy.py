import io
import json
import tarfile
from pathlib import Path

import pytest

from dbs.models import AuditEvent

from dbs.manager.backups.models import BackupFile
from dbs.manager.backups.repositories import BackupFileRepository
from dbs.manager.backups.services import vault_contexts as backup_contexts
from dbs.manager.backups.storage import BackupStorage
from dbs.manager.envfiles.models import EnvVersion
from dbs.manager.envfiles.repositories import EnvVersionRepository
from dbs.manager.envfiles.services import vault_contexts as env_contexts
from dbs.manager.servers.models import Server
from dbs.manager.servers.repositories import ServerRepository
from dbs.manager.servers.services import ServerService
from dbs.manager.servers.services.server_service import DBS_VERSION
from dbs.manager.vault import fingerprint, seal, seal_stream
from tests.manager.remote import scripted_hosts
from tests.manager.servers.support import (
    BACKUP_PASSPHRASE,
    PASSWORD,
    host_key_line,
    private_key_text,
)
from tests.manager.support import logged

REDEPLOY = "/api/redeploy/"
SOURCE = "10.0.0.5"
TARGET = "10.0.0.6"
PYTHON = "/srv/app/.venv/bin/python"
ENV_CONTENT = b"SECRET_KEY=moved\nDEBUG=0\n"
STEPS = ["check", "env", "migrate", "restore", "archives", "final_check"]


def add_server(admin, name, host, **fields):
    return ServerService(admin).create(
        name=name,
        host=host,
        username="deploy",
        auth_method=Server.AuthMethod.KEY,
        private_key=private_key_text(),
        host_key=host_key_line(),
        python_path=PYTHON,
        **fields,
    )


def stored_file(server, name, kind, content, sealed=False):
    storage = BackupStorage()
    storage.directory(server.pk)
    path = storage.sealed_path(server.pk, name) if sealed else f"{server.pk}/{name}"
    with storage.writing(path) as handle:
        if sealed:
            seal_stream(
                io.BytesIO(content), handle, context=backup_contexts.SEALED_FILE
            )
        else:
            handle.write(content)
    return BackupFileRepository().create(
        server=server,
        kind=kind,
        name=name,
        size=len(content),
        sha256="0" * 64,
        storage_path=path,
        sealed=sealed,
        validation=BackupFile.Validation.STRUCTURE_OK,
    )


def archive_bytes():
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        data = b"logo"
        info = tarfile.TarInfo("srv/app/media/logo.png")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


@pytest.fixture
def world(admin, tmp_path, monkeypatch):
    target_root = tmp_path / "target"
    (target_root / "app").mkdir(parents=True)
    source = add_server(admin, "web-1", SOURCE, backup_passphrase=BACKUP_PASSPHRASE)
    target = add_server(
        admin,
        "web-2",
        TARGET,
        project_dir=str(target_root / "app"),
        remote_backup_dir=str(target_root / "backups"),
        env_path=str(target_root / "app" / ".env"),
    )
    backup = stored_file(
        source, "web-1-20261009-030000Z.dbs", BackupFile.Kind.DBS, b"DBS backup"
    )
    archive = stored_file(
        source, "media.tar.gz", BackupFile.Kind.ARCHIVE, archive_bytes(), sealed=True
    )
    version = EnvVersionRepository().create(
        server=source,
        path="/srv/app/.env",
        content_sealed=seal(ENV_CONTENT, context=env_contexts.CONTENT),
        fingerprint=fingerprint(ENV_CONTENT, context=env_contexts.CONTENT),
        size=len(ENV_CONTENT),
        key_names=["SECRET_KEY", "DEBUG"],
        source=EnvVersion.Source.PULLED,
    )
    hosts = scripted_hosts(monkeypatch)
    sent = {"restores": [], "extracted": []}

    def restore(argv, stdin_line):
        path = Path(argv[3])
        sent["restores"].append(
            {
                "name": path.name,
                "argv": argv,
                "stdin": stdin_line,
                "data": path.read_bytes(),
            }
        )
        if "--dry-run" in argv:
            return 0, "12 records and 0 files would be restored\n", ""
        return 0, "Restored 12 records and 0 files\n", ""

    def extract(argv, stdin_line):
        with tarfile.open(argv[2]) as tar:
            sent["extracted"].append({"argv": argv, "members": tar.getnames()})
        return 0, "", ""

    for argv, result in (
        (["uname", "-sr"], (0, "Linux 6.1\n", "")),
        ([PYTHON, "-c", DBS_VERSION], (0, "0.5.0\n", "")),
        ([PYTHON, "manage.py", "dbs_backup", "--help"], (0, "usage\n", "")),
        (
            [PYTHON, "manage.py", "migrate", "--noinput"],
            (0, "No migrations to apply.\n", ""),
        ),
        ([PYTHON, "manage.py", "migrate", "--check", "--noinput"], (0, "", "")),
    ):
        hosts.answer(TARGET, argv, result)
    hosts.answer(TARGET, [PYTHON, "manage.py", "dbs_restore"], restore)
    hosts.answer(TARGET, ["tar", "-xzf"], extract)
    return {
        "source": source,
        "target": target,
        "backup": backup,
        "archive": archive,
        "version": version,
        "hosts": hosts,
        "sent": sent,
        "root": target_root,
    }


def body(world, **fields):
    values = {
        "source_server": str(world["source"].pk),
        "target_server": str(world["target"].pk),
        "backup": str(world["backup"].pk),
        "env_version": None,
        "archives": [],
        "migrate": False,
        "flush": False,
        "rehearsal": True,
    }
    return {**values, **fields}


def job_of(api, response):
    assert response.status_code == 202, response.json()
    assert set(response.json()) == {"activity"}
    return api.get(f"/api/activity/{response.json()['activity']}/").json()


def statuses(job):
    return [(step["step"], step["status"]) for step in job["detail"]["steps"]]


@pytest.mark.django_db
def test_a_rehearsal_checks_and_dry_runs_the_restore_only(api, world, run_jobs):
    with run_jobs():
        response = api.post(REDEPLOY, body(world), format="json")

    job = job_of(api, response)
    assert (job["action"], job["status"], job["error_code"]) == (
        "redeploy.run",
        "succeeded",
        "",
    )
    assert job["server"] == str(world["target"].pk)
    assert statuses(job) == [
        ("check", "succeeded"),
        ("env", "skipped"),
        ("migrate", "skipped"),
        ("restore", "succeeded"),
        ("archives", "skipped"),
        ("final_check", "skipped"),
    ]
    [restore] = world["sent"]["restores"]
    assert "--dry-run" in restore["argv"]
    assert world["sent"]["extracted"] == []
    assert all(
        run["argv"][2:] != ["migrate", "--noinput"]
        for run in world["hosts"].runs(TARGET)
        if len(run["argv"]) > 2
    )


@pytest.mark.django_db
def test_a_rehearsal_onto_an_unmigrated_target_checks_the_backup_here(
    api, world, run_jobs
):
    from dbs.crypto.kdf import KDFParams
    from dbs.engine import create_backup

    world["hosts"].answer(
        TARGET, [PYTHON, "manage.py", "migrate", "--check", "--noinput"], (1, "", "unapplied")
    )
    container = create_backup(
        BACKUP_PASSPHRASE, kdf_params=KDFParams(time_cost=1, memory_cost=8192, parallelism=1)
    )
    real = stored_file(
        world["source"], "web-1-20261009-040000Z.dbs", BackupFile.Kind.DBS, container
    )

    with run_jobs():
        response = api.post(REDEPLOY, body(world, backup=str(real.pk)), format="json")

    job = job_of(api, response)
    assert job["status"] == "succeeded"
    assert ("restore", "succeeded") in statuses(job)
    assert world["sent"]["restores"] == []
    restore = AuditEvent.objects.get(action="redeploy.restore")
    assert restore.data == {"validated": True, "target_not_migrated": True}


@pytest.mark.django_db
def test_the_restore_uses_the_sources_passphrase_on_the_targets_profile(
    api, world, run_jobs
):
    with run_jobs():
        api.post(REDEPLOY, body(world), format="json")

    [restore] = world["sent"]["restores"]
    assert restore["name"].startswith(".dbs-restore-")
    assert restore["stdin"] == BACKUP_PASSPHRASE
    assert restore["data"] == b"DBS backup"
    assert restore["argv"][:3] == [PYTHON, "manage.py", "dbs_restore"]
    assert Path(restore["argv"][3]).parent == world["root"] / "backups"
    assert world["hosts"].runs(SOURCE) == []
    assert not list((world["root"] / "backups").glob(".dbs-restore-*"))


@pytest.mark.django_db
def test_every_step_is_audited_against_the_target(api, world, run_jobs):
    with run_jobs():
        api.post(REDEPLOY, body(world), format="json")

    target = str(world["target"].pk)
    for step in ("check", "restore"):
        [entry] = logged(f"redeploy.{step}")
        assert (entry.subject, entry.status) == (target, "succeeded")
    assert logged("redeploy.migrate") == []


@pytest.mark.django_db
def test_a_redeploy_for_real_runs_every_step(api, world, run_jobs):
    with run_jobs():
        response = api.post(
            REDEPLOY,
            body(
                world,
                rehearsal=False,
                migrate=True,
                flush=True,
                env_version=str(world["version"].pk),
                archives=[str(world["archive"].pk)],
                password=PASSWORD,
                confirm_name="web-2",
            ),
            format="json",
        )

    job = job_of(api, response)
    assert job["status"] == "succeeded", job
    assert statuses(job) == [(step, "succeeded") for step in STEPS]
    assert (world["root"] / "app" / ".env").read_bytes() == ENV_CONTENT
    [restore] = world["sent"]["restores"]
    assert "--flush" in restore["argv"] and "--dry-run" not in restore["argv"]
    [extracted] = world["sent"]["extracted"]
    argv = extracted["argv"]
    assert argv[0:2] == ["tar", "-xzf"] and argv[3:] == ["-C", "/", "--no-same-owner"]
    assert Path(argv[2]).name.startswith(".dbs-extract-")
    assert extracted["members"] == ["srv/app/media/logo.png"]
    migrations = [
        run for run in world["hosts"].runs(TARGET) if "migrate" in run["argv"]
    ]
    assert [run["argv"] for run in migrations] == [
        [PYTHON, "manage.py", "migrate", "--noinput"]
    ]
    for step in STEPS:
        assert logged(f"redeploy.{step}")[0].subject == str(world["target"].pk)


@pytest.mark.django_db
def test_archives_land_in_the_targets_project_folder(api, world, run_jobs):
    ServerRepository().update(world["source"], project_dir="/srv/app")
    target_dir = world["target"].project_dir.strip("/")

    with run_jobs():
        response = api.post(
            REDEPLOY,
            body(
                world,
                rehearsal=False,
                archives=[str(world["archive"].pk)],
                password=PASSWORD,
                confirm_name="web-2",
            ),
            format="json",
        )

    assert job_of(api, response)["status"] == "succeeded"
    [extracted] = world["sent"]["extracted"]
    assert extracted["argv"][6:] == [f"--transform=s|^srv/app/|{target_dir}/|"]


@pytest.mark.django_db
def test_a_failing_step_fails_the_job_and_skips_the_rest(api, world, run_jobs):
    world["hosts"].answer(
        TARGET, [PYTHON, "manage.py", "migrate", "--noinput"], (1, "", "boom")
    )

    with run_jobs():
        response = api.post(
            REDEPLOY,
            body(
                world,
                rehearsal=False,
                migrate=True,
                password=PASSWORD,
                confirm_name="web-2",
            ),
            format="json",
        )

    job = job_of(api, response)
    assert (job["status"], job["error_code"]) == ("failed", "remote_command_failed")
    assert statuses(job) == [
        ("check", "succeeded"),
        ("env", "skipped"),
        ("migrate", "failed"),
        ("restore", "skipped"),
        ("archives", "skipped"),
        ("final_check", "skipped"),
    ]
    assert world["sent"]["restores"] == []
    assert logged("redeploy.migrate")[0].status == "failed"


@pytest.mark.django_db
def test_a_target_without_the_project_is_not_ready(api, world, run_jobs):
    world["hosts"].answer(
        TARGET, [PYTHON, "manage.py", "dbs_backup", "--help"], (1, "", "no")
    )

    with run_jobs():
        response = api.post(REDEPLOY, body(world), format="json")

    job = job_of(api, response)
    assert (job["status"], job["error_code"]) == ("failed", "target_not_ready")


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("fields", "code"),
    [
        (
            {"rehearsal": False, "password": PASSWORD, "confirm_name": "web-1"},
            "confirm_name_mismatch",
        ),
        (
            {"rehearsal": False, "password": "wrong", "confirm_name": "web-2"},
            "invalid_password",
        ),
    ],
)
def test_a_redeploy_for_real_needs_the_name_and_the_password(api, world, fields, code):
    response = api.post(REDEPLOY, body(world, **fields), format="json")

    assert response.json()["error"]["code"] == code
    assert logged("redeploy.check") == []


@pytest.mark.django_db
def test_a_refused_password_is_audited(api, world):
    api.post(
        REDEPLOY,
        body(world, rehearsal=False, password="wrong", confirm_name="web-2"),
        format="json",
    )

    [entry] = logged("redeploy.run")
    assert (entry.status, entry.error_code) == ("failed", "invalid_password")
    assert entry.subject == str(world["target"].pk)


@pytest.mark.django_db
def test_a_redeploy_for_real_without_a_password_names_the_field(api, world):
    response = api.post(
        REDEPLOY, body(world, rehearsal=False, confirm_name="web-2"), format="json"
    )

    assert response.json()["error"]["fields"] == {"password": ["required"]}


@pytest.mark.django_db
def test_the_source_and_target_must_differ(api, world):
    response = api.post(
        REDEPLOY, body(world, target_server=str(world["source"].pk)), format="json"
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "same_server"


@pytest.mark.django_db
def test_a_source_without_a_stored_passphrase_cannot_be_moved(api, world):
    ServerRepository().update(world["source"], backup_passphrase_sealed=None)

    response = api.post(REDEPLOY, body(world), format="json")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "passphrase_missing"


@pytest.mark.django_db
def test_files_must_belong_to_the_source(api, world, admin):
    other = stored_file(world["target"], "other.dbs", BackupFile.Kind.DBS, b"x")

    response = api.post(REDEPLOY, body(world, backup=str(other.pk)), format="json")

    assert response.json()["error"]["fields"] == {"backup": ["not_found"]}


@pytest.mark.django_db
def test_a_backup_restores_onto_another_server_with_its_own_passphrase(
    api, world, run_jobs
):
    with run_jobs():
        response = api.post(
            f"/api/backups/{world['backup'].pk}/restore/",
            {
                "mode": "merge",
                "rehearse": True,
                "target_server": str(world["target"].pk),
            },
            format="json",
        )

    job = job_of(api, response)
    assert job["status"] == "succeeded", job
    assert job["server"] == str(world["target"].pk)
    assert job["detail"]["target_server"] == str(world["target"].pk)
    [restore] = world["sent"]["restores"]
    assert restore["stdin"] == BACKUP_PASSPHRASE
    assert restore["name"].startswith(".dbs-restore-")


@pytest.mark.django_db
def test_a_restore_for_real_onto_another_server_confirms_the_targets_name(api, world):
    response = api.post(
        f"/api/backups/{world['backup'].pk}/restore/",
        {
            "mode": "replace",
            "rehearse": False,
            "account_password": PASSWORD,
            "server_name": "web-1",
            "target_server": str(world["target"].pk),
        },
        format="json",
    )

    assert response.json()["error"]["fields"] == {"server_name": ["name_mismatch"]}


@pytest.mark.django_db
def test_a_restore_without_the_sources_passphrase_is_refused(api, world):
    ServerRepository().update(world["source"], backup_passphrase_sealed=None)

    response = api.post(
        f"/api/backups/{world['backup'].pk}/restore/",
        {"mode": "merge", "rehearse": True, "target_server": str(world["target"].pk)},
        format="json",
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "passphrase_missing"
    assert json.dumps(response.json()).count("passphrase_missing") == 1
