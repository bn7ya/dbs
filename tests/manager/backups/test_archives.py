from __future__ import annotations

import hashlib
import re
import stat

import pytest

from dbs import audit
from dbs.manager import vault
from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.backups.models import BackupFile
from dbs.manager.backups.repositories import BackupFileRepository, BackupPlanRepository
from dbs.manager.backups.services import BackupRunService
from dbs.manager.backups.storage import BackupStorage
from dbs.manager.servers.exceptions import RemoteCommandFailed, SSHUnreachable
from dbs.manager.vault import VaultError
from tests.manager.backups.support import (
    ARCHIVED_PATHS,
    SERVER_FILES,
    TAR_FAILURE,
    BackupHost,
    archived_files,
)
from tests.manager.servers.support import BACKUP_DIR, connecting_to

CONNECT = "dbs.manager.servers.services.connection_service.connect"
NAME = re.compile(r"web-1-files-\d{8}-\d{6}Z(?:-\d+)?\.tar\.gz")


@pytest.fixture
def archive_plan(make_plan):

    def make(**fields):
        return make_plan(
            **({"name": "files", "kind": "archive", "paths": ARCHIVED_PATHS} | fields)
        )

    return make


@pytest.fixture
def archived(ran):

    def run(plan) -> BackupFile:
        job = ran(plan)
        assert job.status == audit.SUCCEEDED, job.error_code
        return BackupFileRepository().get(job.data["backup"])

    return run


def using(monkeypatch, host: BackupHost) -> BackupHost:
    monkeypatch.setattr(CONNECT, connecting_to(host))
    return host


def stored_files(storage) -> list[str]:
    return sorted(path.name for path in storage.rglob("*") if path.is_file())


def logged(action: str):
    return list(ActivityRepository().filtered(action=action))


def flip(path, position: int) -> None:
    data = bytearray(path.read_bytes())
    data[position] ^= 0x01
    path.write_bytes(bytes(data))


@pytest.mark.django_db
def test_an_archive_is_stored_sealed_and_described(
    settings, admin, server, host, storage, archive_plan, ran
):
    plan = archive_plan(keep_remote=1)

    job = ran(plan)

    assert job.status == audit.SUCCEEDED
    backup = BackupFileRepository().get(job.data["backup"])
    [made] = host.archives
    assert job.data == {
        "plan": str(plan.pk),
        "backup": str(backup.pk),
        "size": len(made.content),
    }
    assert (made.paths, made.remote_dir, made.name) == (
        ARCHIVED_PATHS,
        BACKUP_DIR,
        backup.name,
    )
    assert made.timeout == settings.BACKUP_EXEC_TIMEOUT
    assert NAME.fullmatch(backup.name)
    assert (backup.kind, backup.sealed, backup.plan, backup.created_by) == (
        "archive",
        True,
        plan,
        admin,
    )
    assert backup.size == len(made.content)
    assert backup.sha256 == hashlib.sha256(made.content).hexdigest()
    assert backup.storage_path == f"{server.pk}/{backup.name}.sealed"
    assert backup.remote_path == f"{BACKUP_DIR}/{backup.name}"
    assert backup.validation == BackupFile.Validation.STRUCTURE_OK
    on_disk = storage / backup.storage_path
    assert stat.S_IMODE(on_disk.stat().st_mode) == 0o600
    assert on_disk.read_bytes().startswith(vault.STREAM_MAGIC)
    assert made.content not in on_disk.read_bytes()


@pytest.mark.django_db
def test_nothing_but_the_sealed_file_is_written_here(storage, archive_plan, archived):
    backup = archived(archive_plan())

    assert stored_files(storage) == [f"{backup.name}.sealed"]


@pytest.mark.django_db
def test_an_archive_downloads_as_the_archive_the_server_made(
    api, admin, host, archive_plan, archived
):
    backup = archived(archive_plan())

    response = api.get(f"/api/backups/{backup.pk}/download/")

    assert response.status_code == 200
    content = b"".join(response.streaming_content)
    assert content == host.archives[0].content
    assert archived_files(content) == {
        path: data
        for path, data in SERVER_FILES.items()
        if path.startswith(("/srv", "/etc"))
    }
    assert response["Content-Type"] == "application/octet-stream"
    assert response["Content-Disposition"] == f'attachment; filename="{backup.name}"'
    assert response["Content-Length"] == str(backup.size)
    assert response["Cache-Control"] == "no-store"
    [entry] = logged("backup.download")
    assert (entry.target_name, entry.actor) == (backup.name, admin)


@pytest.mark.django_db
def test_an_archive_of_several_chunks_downloads_whole(
    monkeypatch, api, host, archive_plan, archived
):
    monkeypatch.setattr(vault, "CHUNK_BYTES", 64)
    backup = archived(archive_plan())

    response = api.get(f"/api/backups/{backup.pk}/download/")

    assert backup.size > 3 * 64
    assert b"".join(response.streaming_content) == host.archives[0].content


@pytest.mark.django_db
def test_an_archive_lists_with_its_kind(api, server, archive_plan, archived):
    backup = archived(archive_plan())

    [listed] = api.get("/api/backups/", {"server": server.pk}).json()["results"]

    assert (listed["id"], listed["kind"], listed["name"]) == (
        str(backup.pk),
        "archive",
        backup.name,
    )
    assert "sealed" not in listed


@pytest.mark.django_db
def test_a_file_that_changed_while_it_was_archived_is_a_warning(
    monkeypatch, server_root, archive_plan, ran
):
    using(monkeypatch, BackupHost(root=server_root, tar_status=1))
    plan = archive_plan()

    job = ran(plan)

    assert job.status == audit.SUCCEEDED
    assert job.data["warning"] == "files_changed"
    assert BackupFileRepository().find(job.data["backup"]) is not None
    assert BackupPlanRepository().get(plan.pk).last_status == "succeeded"


@pytest.mark.django_db
def test_an_archive_tar_could_not_make_fails_with_its_output(
    monkeypatch, server_root, storage, archive_plan, ran
):
    using(monkeypatch, BackupHost(root=server_root, tar_status=2))
    plan = archive_plan()

    job = ran(plan)

    assert (job.status, job.error_code) == (audit.FAILED, "archive_failed")
    assert job.data == {"plan": str(plan.pk), "output": TAR_FAILURE}
    assert BackupPlanRepository().get(plan.pk).last_error_code == "archive_failed"
    assert stored_files(storage) == []


@pytest.mark.django_db
def test_an_archive_that_arrives_changed_is_not_kept(
    monkeypatch, server, server_root, storage, archive_plan, ran
):
    host = using(monkeypatch, BackupHost(root=server_root, reported_sha256="0" * 64))
    plan = archive_plan(keep_remote=0)

    job = ran(plan)

    assert (job.status, job.error_code) == (audit.FAILED, "archive_mismatch")
    assert job.data == {"plan": str(plan.pk)}
    assert BackupFileRepository().alive_for_server(server.pk).count() == 0
    assert stored_files(storage) == []
    assert host.prunes == []
    assert host.remote_names() == [host.archives[0].name]


@pytest.mark.django_db
def test_an_archive_plan_that_cannot_reach_its_server_fails_like_a_take(
    monkeypatch, server_root, storage, archive_plan, ran
):
    using(monkeypatch, BackupHost(root=server_root, failure=SSHUnreachable()))

    job = ran(archive_plan())

    assert job.error_code == "ssh_unreachable"
    assert stored_files(storage) == []


@pytest.mark.django_db
def test_an_archive_that_cannot_be_recorded_does_not_stay_on_disk(
    monkeypatch, storage, archive_plan, ran
):
    def refuse(self, **fields):
        raise RuntimeError("database gone")

    monkeypatch.setattr(BackupFileRepository, "create", refuse)

    with pytest.raises(RuntimeError):
        ran(archive_plan())

    assert stored_files(storage) == []


@pytest.mark.django_db
def test_an_archive_whose_server_copies_cannot_be_pruned_is_not_kept(
    monkeypatch, server_root, storage, archive_plan, ran
):
    host = using(monkeypatch, BackupHost(root=server_root))

    def refuse(remote_dir, pattern, keep):
        raise RemoteCommandFailed(output="/var/backups: Permission denied")

    host.prune = refuse

    job = ran(archive_plan())

    assert (job.error_code, job.data["output"]) == (
        "remote_command_failed",
        "/var/backups: Permission denied",
    )
    assert stored_files(storage) == []


@pytest.mark.django_db
def test_keeping_no_copy_on_the_server_removes_the_archive_once_fetched(
    host, archive_plan, archived
):
    backup = archived(archive_plan(keep_remote=0))

    assert backup.remote_path == ""
    assert host.remote_names() == []
    [prune] = host.prunes
    assert (prune.remote_dir, prune.keep) == (BACKUP_DIR, 0)


@pytest.mark.django_db
def test_the_server_keeps_the_plans_newest_archives_and_nothing_else_is_touched(
    host, server_root, archive_plan, archived
):
    plan = archive_plan(keep_remote=2)
    other = archive_plan(name="files-2", keep_remote=5)
    unrelated = (
        server_root / BACKUP_DIR.lstrip("/") / "web-1-files-20261001-120000Z.dbs"
    )
    unrelated.parent.mkdir(parents=True, exist_ok=True)
    unrelated.write_bytes(b"a dbs backup")
    others = archived(other)

    names = [archived(plan).name for _ in range(3)]

    assert host.remote_names() == sorted([*names[1:], others.name, unrelated.name])
    *_, last = host.prunes
    assert (last.remote_dir, last.keep) == (BACKUP_DIR, 2)
    assert all(last.pattern.fullmatch(name) for name in names)
    assert not last.pattern.fullmatch(others.name)
    assert not last.pattern.fullmatch(unrelated.name)


@pytest.mark.django_db
def test_two_archives_of_one_second_get_their_own_names(
    storage, archive_plan, archived
):
    plan = archive_plan(keep=5)

    first, second = archived(plan), archived(plan)

    assert first.name != second.name
    assert first.storage_path != second.storage_path


@pytest.mark.django_db
def test_an_archive_plan_keeps_its_newest_files_and_deletes_the_rest(
    server, storage, archive_plan, archived, make_plan, ran
):
    plan = archive_plan(keep=2)
    dbs_plan = make_plan(keep=1)
    ran(dbs_plan)
    oldest, middle, newest = (archived(plan) for _ in range(3))

    alive = [file.pk for file in BackupFileRepository().alive_for_plan(plan.pk)]
    assert alive == [newest.pk, middle.pk]
    assert BackupFileRepository().alive_for_plan(dbs_plan.pk).count() == 1
    [retention] = logged("backup.retention")
    assert retention.data == {"removed": [oldest.name], "plan": "files"}
    assert (storage / oldest.storage_path).is_file()


def verified(api, run_jobs, entry, backup):
    with run_jobs():
        response = api.post(f"/api/backups/{backup.pk}/verify/")
    return entry(response.json()["activity"])


@pytest.mark.django_db
def test_a_sealed_archive_that_opens_whole_is_verified(
    api, run_jobs, entry, archive_plan, archived
):
    backup = archived(archive_plan())

    job = verified(api, run_jobs, entry, backup)

    assert (job.status, job.data) == (
        audit.SUCCEEDED,
        {"validation": "verified"},
    )
    assert (
        BackupFileRepository().get(backup.pk).validation
        == BackupFile.Validation.VERIFIED
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "position", [0, vault.STREAM_HEADER_BYTES + 3, -1], ids=["header", "chunk", "tag"]
)
def test_a_sealed_archive_altered_on_disk_fails_verification(
    api, run_jobs, entry, storage, archive_plan, archived, position
):
    backup = archived(archive_plan())
    flip(storage / backup.storage_path, position)

    job = verified(api, run_jobs, entry, backup)

    assert (job.status, job.data) == (
        audit.SUCCEEDED,
        {"validation": "failed"},
    )
    assert (
        BackupFileRepository().get(backup.pk).validation == BackupFile.Validation.FAILED
    )


@pytest.mark.django_db
def test_a_sealed_archive_whose_digest_disagrees_fails_verification(
    api, run_jobs, entry, archive_plan, archived
):
    backup = archived(archive_plan())
    BackupFileRepository().update(backup, sha256="0" * 64)

    job = verified(api, run_jobs, entry, backup)

    assert job.data == {"validation": "failed"}


@pytest.mark.django_db
def test_a_sealed_archive_whose_key_is_gone_fails_verification(
    api, run_jobs, entry, archive_plan, archived, monkeypatch
):
    backup = archived(archive_plan())
    monkeypatch.setattr(vault, "_keys", lambda: [b"another-data-directory-key-32-by"])

    job = verified(api, run_jobs, entry, backup)

    assert job.data == {"validation": "failed"}


@pytest.mark.django_db
def test_a_sealed_archive_that_left_the_disk_fails_the_verify_job(
    api, run_jobs, entry, archive_plan, archived
):
    backup = archived(archive_plan())
    BackupStorage().remove(backup.storage_path)

    job = verified(api, run_jobs, entry, backup)

    assert (job.status, job.error_code) == (audit.FAILED, "backup_missing")


@pytest.mark.django_db
def test_a_finished_verify_of_an_archive_is_not_run_twice(
    api, run_jobs, entry, archive_plan, archived
):
    backup = archived(archive_plan())
    job = verified(api, run_jobs, entry, backup)
    verified_at = BackupFileRepository().get(backup.pk).validated_at

    BackupRunService().verify(job.pk, backup.pk)

    assert BackupFileRepository().get(backup.pk).validated_at == verified_at


@pytest.mark.django_db
def test_a_sealed_archive_that_does_not_open_is_not_downloaded_or_logged(
    api, storage, archive_plan, archived
):
    backup = archived(archive_plan())
    flip(storage / backup.storage_path, 0)

    with pytest.raises(VaultError):
        api.get(f"/api/backups/{backup.pk}/download/")

    assert logged("backup.download") == []


@pytest.mark.django_db
def test_a_download_stops_at_a_chunk_altered_on_disk(
    monkeypatch, api, host, storage, archive_plan, archived
):
    monkeypatch.setattr(vault, "CHUNK_BYTES", 64)
    backup = archived(archive_plan())
    flip(storage / backup.storage_path, -1)
    received = []

    response = api.get(f"/api/backups/{backup.pk}/download/")
    with pytest.raises(VaultError):
        for chunk in response.streaming_content:
            received.append(chunk)

    assert b"".join(received) == host.archives[0].content[: len(b"".join(received))]
    assert len(b"".join(received)) < backup.size
