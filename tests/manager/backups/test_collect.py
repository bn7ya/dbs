from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import replace
from datetime import datetime
from datetime import timezone as dt_timezone

import pytest

from dbs import audit
from dbs.manager import vault
from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.backups.models import BackupFile
from dbs.manager.backups.repositories import BackupFileRepository, BackupPlanRepository
from dbs.manager.servers.exceptions import (
    RemoteCommandFailed,
    RemoteNotFound,
    RemotePermissionDenied,
    SSHUnreachable,
)
from tests.manager.backups.support import BackupHost
from tests.manager.servers.support import connecting_to

CONNECT = "dbs.manager.servers.services.connection_service.connect"
DUMPS = "/var/backups/pg"
FIRST = ("db-20261001.sql.gz", b"first dump", 1_790_000_000)
SECOND = ("db-20261002.sql.gz", b"second dump, a little longer", 1_790_086_400)
THIRD = ("db-20261003.sql.gz", b"third dump", 1_790_172_800)
REWRITTEN = b"second dump, written again"


def put(server_root, name: str, content: bytes, mtime: int) -> None:
    path = server_root / DUMPS.lstrip("/") / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    os.utime(path, (mtime, mtime))


def moment(mtime: int) -> datetime:
    return datetime.fromtimestamp(mtime, dt_timezone.utc)


def on_server(server_root) -> dict[str, tuple[bytes, int]]:
    return {
        str(path.relative_to(server_root)): (
            os.readlink(path).encode() if path.is_symlink() else path.read_bytes(),
            path.lstat().st_mtime_ns,
        )
        for path in server_root.rglob("*")
        if path.is_symlink() or path.is_file()
    }


def stored_files(storage) -> list[str]:
    return sorted(path.name for path in storage.rglob("*") if path.is_file())


def logged(action: str):
    return list(ActivityRepository().filtered(action=action))


def names(rows) -> list[str]:
    return [row.name for row in rows]


@pytest.fixture
def dumps(server_root):
    for name, content, mtime in (FIRST, SECOND):
        put(server_root, name, content, mtime)
    put(server_root, "notes.txt", b"not a dump", FIRST[2])
    folder = server_root / DUMPS.lstrip("/")
    (folder / "latest.sql.gz").symlink_to(folder / SECOND[0])
    (folder / "archive.sql.gz").mkdir()
    (folder / "archive.sql.gz" / "inside.sql.gz").write_bytes(b"nested")
    return server_root


@pytest.fixture
def collect_plan(make_plan):

    def make(**fields):
        values = {
            "name": "pg-dumps",
            "kind": "collect",
            "paths": [DUMPS],
            "pattern": "*.sql.gz",
        }
        return make_plan(**(values | fields))

    return make


@pytest.fixture
def collected(ran):

    def run(plan) -> dict:
        job = ran(plan)
        assert job.status == audit.SUCCEEDED, job.error_code
        return job.data

    return run


def alive(plan) -> list[BackupFile]:
    return list(BackupFileRepository().alive_for_plan(plan.pk))


@pytest.mark.django_db
def test_a_first_run_collects_each_matching_file_sealed_and_described(
    admin, server, host, dumps, storage, collect_plan, ran
):
    plan = collect_plan()

    job = ran(plan)

    assert job.status == audit.SUCCEEDED
    assert job.data == {
        "plan": str(plan.pk),
        "collected": 2,
        "skipped": 0,
        "size": len(FIRST[1]) + len(SECOND[1]),
    }
    second, first = alive(plan)
    for row, (name, content, mtime) in ((first, FIRST), (second, SECOND)):
        assert (row.kind, row.name, row.sealed) == ("collected", name, True)
        assert (row.plan, row.server, row.created_by) == (plan, server, admin)
        assert (row.remote_path, row.remote_size) == (f"{DUMPS}/{name}", len(content))
        assert row.remote_mtime == moment(mtime)
        assert (row.size, row.sha256) == (
            len(content),
            hashlib.sha256(content).hexdigest(),
        )
        assert row.storage_path == f"{server.pk}/{name}.sealed"
        assert row.validation == BackupFile.Validation.STRUCTURE_OK
        on_disk = storage / row.storage_path
        assert stat.S_IMODE(on_disk.stat().st_mode) == 0o600
        assert on_disk.read_bytes().startswith(vault.STREAM_MAGIC)
        assert content not in on_disk.read_bytes()
    assert stored_files(storage) == [f"{FIRST[0]}.sealed", f"{SECOND[0]}.sealed"]


@pytest.mark.django_db
def test_links_and_folders_are_never_collected(host, dumps, collect_plan, collected):
    plan = collect_plan(pattern="*")

    detail = collected(plan)

    assert detail["collected"] == 3
    assert sorted(names(alive(plan))) == [FIRST[0], SECOND[0], "notes.txt"]


@pytest.mark.django_db
def test_a_pattern_matches_the_whole_name_and_its_case(
    host, server_root, dumps, collect_plan, collected
):
    put(server_root, "DB-20261004.SQL.GZ", b"shouting", THIRD[2])
    put(server_root, "db-20261005.sql.gz.part", b"half", THIRD[2])

    detail = collected(collect_plan(pattern="db-*.sql.gz"))

    assert (detail["collected"], detail["skipped"]) == (2, 0)


@pytest.mark.django_db
def test_a_folder_with_nothing_that_matches_is_a_run_that_collected_nothing(
    host, dumps, collect_plan, collected
):
    plan = collect_plan(pattern="*.dump")

    detail = collected(plan)

    assert detail == {"plan": str(plan.pk), "collected": 0, "skipped": 0, "size": 0}
    assert BackupPlanRepository().get(plan.pk).last_status == "succeeded"


@pytest.mark.django_db
def test_a_second_run_with_nothing_new_succeeds_and_collects_nothing(
    host, dumps, storage, collect_plan, collected
):
    plan = collect_plan()
    collected(plan)
    before = stored_files(storage)

    detail = collected(plan)

    assert detail == {"plan": str(plan.pk), "collected": 0, "skipped": 2, "size": 0}
    assert stored_files(storage) == before
    assert len(alive(plan)) == 2


@pytest.mark.django_db
def test_a_new_file_is_collected_beside_the_ones_already_here(
    host, server_root, dumps, collect_plan, collected
):
    plan = collect_plan()
    collected(plan)
    put(server_root, *THIRD)

    detail = collected(plan)

    assert (detail["collected"], detail["skipped"], detail["size"]) == (
        1,
        2,
        len(THIRD[1]),
    )
    assert names(alive(plan)) == [THIRD[0], SECOND[0], FIRST[0]]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("content", "mtime"),
    [(SECOND[1], SECOND[2] + 1), (SECOND[1] + b"!", SECOND[2])],
    ids=["touched", "same-time-new-size"],
)
def test_a_new_size_or_a_new_time_alone_makes_a_file_new(
    host, server_root, dumps, collect_plan, collected, content, mtime
):
    plan = collect_plan()
    collected(plan)
    put(server_root, SECOND[0], content, mtime)

    detail = collected(plan)

    assert (detail["collected"], detail["skipped"]) == (1, 1)


@pytest.mark.django_db
def test_a_file_that_changed_is_collected_again_and_both_download_as_they_were(
    api, host, server, server_root, dumps, collect_plan, collected
):
    plan = collect_plan()
    collected(plan)
    put(server_root, SECOND[0], REWRITTEN, SECOND[2] + 60)

    detail = collected(plan)

    assert (detail["collected"], detail["skipped"]) == (1, 1)
    again, before, _ = alive(plan)
    assert again.name == before.name == SECOND[0]
    assert (again.remote_size, again.remote_mtime) == (
        len(REWRITTEN),
        moment(SECOND[2] + 60),
    )
    assert before.storage_path == f"{server.pk}/{SECOND[0]}.sealed"
    assert again.storage_path == f"{server.pk}/{SECOND[0]}-2.sealed"
    for row, content in ((before, SECOND[1]), (again, REWRITTEN)):
        response = api.get(f"/api/backups/{row.pk}/download/")
        assert b"".join(response.streaming_content) == content


@pytest.mark.django_db
def test_a_file_a_person_deleted_is_not_collected_again(
    api, host, dumps, collect_plan, collected
):
    plan = collect_plan()
    collected(plan)
    _, first = alive(plan)
    api.delete(f"/api/backups/{first.pk}/")

    detail = collected(plan)

    assert (detail["collected"], detail["skipped"]) == (0, 2)
    assert names(alive(plan)) == [SECOND[0]]
    assert BackupFileRepository().find_including_deleted(first.pk).is_deleted


@pytest.mark.django_db
def test_another_plan_collects_the_same_files_for_itself(
    host, dumps, collect_plan, collected
):
    first_plan = collect_plan()
    collected(first_plan)

    detail = collected(collect_plan(name="pg-dumps-2"))

    assert (detail["collected"], detail["skipped"]) == (2, 0)


@pytest.mark.django_db
def test_the_server_is_never_changed(host, server_root, dumps, collect_plan, collected):
    plan = collect_plan(keep=1, pattern="*")
    before = on_server(server_root)

    collected(plan)
    collected(plan)

    assert on_server(server_root) == before
    assert host.prunes == []
    assert logged("backup.retention") != []


@pytest.mark.django_db
def test_a_folder_that_is_not_on_the_server_fails_with_remote_not_found(
    host, dumps, storage, collect_plan, ran
):
    plan = collect_plan(paths=["/var/backups/gone"])

    job = ran(plan)

    assert (job.status, job.error_code) == (audit.FAILED, "remote_not_found")
    assert job.data == {"plan": str(plan.pk)}
    assert BackupPlanRepository().get(plan.pk).last_error_code == "remote_not_found"
    assert stored_files(storage) == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("error", "code"),
    [
        (RemoteNotFound(), "remote_not_found"),
        (RemotePermissionDenied(), "remote_permission_denied"),
        (RemoteCommandFailed(), "remote_command_failed"),
        (SSHUnreachable(), "ssh_unreachable"),
    ],
)
def test_a_folder_that_cannot_be_listed_fails_the_run_with_its_code(
    monkeypatch, server_root, dumps, collect_plan, ran, error, code
):
    monkeypatch.setattr(
        CONNECT, connecting_to(BackupHost(root=server_root, failure=error))
    )

    job = ran(collect_plan())

    assert (job.status, job.error_code) == (audit.FAILED, code)


@pytest.mark.django_db
def test_a_file_that_fails_fails_the_run_and_keeps_the_files_before_it(
    host, dumps, storage, collect_plan, ran, collected
):
    plan = collect_plan(keep=1)
    reading = host.open_file

    def open_file(path):
        if path.endswith(SECOND[0]):
            raise RemoteCommandFailed(output=f"{path}: Connection reset")
        return reading(path)

    host.open_file = open_file

    job = ran(plan)

    assert (job.status, job.error_code) == (
        audit.FAILED,
        "remote_command_failed",
    )
    assert job.data == {
        "plan": str(plan.pk),
        "output": f"{DUMPS}/{SECOND[0]}: Connection reset",
    }
    assert names(alive(plan)) == [FIRST[0]]
    assert stored_files(storage) == [f"{FIRST[0]}.sealed"]
    assert logged("backup.retention") == []

    host.open_file = reading
    detail = collected(plan)

    assert (detail["collected"], detail["skipped"]) == (1, 1)


@pytest.mark.django_db
def test_a_file_still_being_written_is_left_for_a_later_run(
    host, dumps, storage, collect_plan, collected
):
    plan = collect_plan()
    listing = host.list_files

    def growing(folder):
        return [
            replace(found, size=found.size - 4) if found.name == SECOND[0] else found
            for found in listing(folder)
        ]

    host.list_files = growing

    detail = collected(plan)

    assert (detail["collected"], detail["skipped"], detail["size"]) == (
        1,
        1,
        len(FIRST[1]),
    )
    assert stored_files(storage) == [f"{FIRST[0]}.sealed"]

    host.list_files = listing
    detail = collected(plan)

    assert (detail["collected"], detail["skipped"]) == (1, 1)


@pytest.mark.django_db
def test_a_collected_file_that_cannot_be_recorded_does_not_stay_on_disk(
    monkeypatch, host, dumps, storage, collect_plan, ran
):
    def refuse(self, **fields):
        raise RuntimeError("database gone")

    monkeypatch.setattr(BackupFileRepository, "create", refuse)

    with pytest.raises(RuntimeError):
        ran(collect_plan())

    assert stored_files(storage) == []


@pytest.mark.django_db
def test_a_collect_plan_keeps_its_newest_files_and_never_brings_back_the_rest(
    host, server, server_root, dumps, storage, collect_plan, collected, make_plan, ran
):
    plan = collect_plan(keep=2)
    dbs_plan = make_plan(keep=1)
    ran(dbs_plan)
    put(server_root, *THIRD)

    collected(plan)

    assert names(alive(plan)) == [THIRD[0], SECOND[0]]
    [retention] = logged("backup.retention")
    assert retention.data == {"removed": [FIRST[0]], "plan": "pg-dumps"}
    assert len(alive(dbs_plan)) == 1
    assert (storage / str(server.pk) / f"{FIRST[0]}.sealed").is_file()

    detail = collected(plan)

    assert (detail["collected"], detail["skipped"]) == (0, 3)
    assert len(logged("backup.retention")) == 1


@pytest.mark.django_db
def test_files_of_one_moment_are_newest_by_the_servers_time_then_by_name(
    host, server_root, dumps, collect_plan, collected
):
    plan = collect_plan(pattern="*")
    put(server_root, "db-b.sql.gz", b"b", SECOND[2])
    collected(plan)
    files = BackupFileRepository()
    one_moment = alive(plan)[0].created_at
    for row in alive(plan):
        files.update(row, created_at=one_moment)

    assert names(alive(plan)) == ["db-b.sql.gz", SECOND[0], "notes.txt", FIRST[0]]


@pytest.mark.django_db
def test_a_collected_file_lists_with_its_kind_and_where_it_was_found(
    api, server, host, dumps, collect_plan, collected
):
    plan = collect_plan(pattern=FIRST[0])
    collected(plan)

    [listed] = api.get("/api/backups/", {"server": server.pk}).json()["results"]

    assert (listed["kind"], listed["name"], listed["remote_path"]) == (
        "collected",
        FIRST[0],
        f"{DUMPS}/{FIRST[0]}",
    )
    assert (listed["plan"], listed["plan_name"]) == (str(plan.pk), "pg-dumps")
    assert not {"remote_size", "remote_mtime", "sealed"} & set(listed)


@pytest.mark.django_db
def test_a_collected_file_downloads_as_it_was_on_the_server(
    monkeypatch, api, host, dumps, collect_plan, collected
):
    monkeypatch.setattr(vault, "CHUNK_BYTES", 8)
    plan = collect_plan(pattern=SECOND[0])
    collected(plan)
    [row] = alive(plan)

    response = api.get(f"/api/backups/{row.pk}/download/")

    assert b"".join(response.streaming_content) == SECOND[1]
    assert response["Content-Disposition"] == f'attachment; filename="{SECOND[0]}"'
    assert response["Content-Length"] == str(len(SECOND[1]))


@pytest.mark.django_db
def test_a_collected_file_that_opens_whole_is_verified(
    api, run_jobs, entry, host, dumps, collect_plan, collected
):
    plan = collect_plan(pattern=FIRST[0])
    collected(plan)
    [row] = alive(plan)

    with run_jobs():
        response = api.post(f"/api/backups/{row.pk}/verify/")

    job = entry(response.json()["activity"])
    assert (job.status, job.data) == (
        audit.SUCCEEDED,
        {"validation": "verified"},
    )


@pytest.mark.django_db
def test_a_name_is_kept_without_its_unprintable_characters(
    host, server_root, collect_plan, collected
):
    disguised = "invoice\u202egpj.exe"
    unreadable = "\x1b\x07"
    for name in (disguised, unreadable):
        put(server_root, name, b"content", FIRST[2])
    plan = collect_plan(pattern="*")

    collected(plan)
    again = collected(plan)

    rows = alive(plan)
    assert sorted(names(rows)) == ["collected-file", "invoicegpj.exe"]
    assert sorted(row.remote_path for row in rows) == sorted(
        f"{DUMPS}/{name}" for name in (disguised, unreadable)
    )
    assert again["collected"] == 0
