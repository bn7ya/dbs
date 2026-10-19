from __future__ import annotations

import hashlib
import os
import stat
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from uuid import uuid4

import pytest

from dbs.manager.backups.storage import BackupStorage


def mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.fixture
def permissive_umask():
    before = os.umask(0o000)
    yield
    os.umask(before)


def test_an_applications_directory_is_private_whatever_the_umask(
    storage, permissive_umask
):
    application_id = uuid4()

    directory = BackupStorage().directory(application_id)

    assert directory == storage / str(application_id)
    assert mode(directory) == 0o700
    assert mode(storage) == 0o700
    assert BackupStorage().directory(application_id) == directory


def test_a_received_file_is_private_described_and_installed_under_its_name(
    storage, permissive_umask
):
    application_id = uuid4()
    files = BackupStorage()

    with files.receiving(application_id) as incoming:
        incoming.write(b"backup ")
        incoming.write(b"bytes")
        assert incoming.path.name.endswith(".part")
        assert mode(incoming.path) == 0o600
        kept = files.install(incoming, application_id, "web-1-20261001-120000Z.dbs")

    stored = storage / str(application_id) / "web-1-20261001-120000Z.dbs"
    assert kept.relative_path == f"{application_id}/{stored.name}"
    assert kept.size == len(b"backup bytes")
    assert kept.sha256 == hashlib.sha256(b"backup bytes").hexdigest()
    assert stored.read_bytes() == b"backup bytes"
    assert mode(stored) == 0o600
    assert sorted(os.listdir(stored.parent)) == [stored.name]


def test_an_installed_file_never_replaces_one_already_there(storage):
    application_id = uuid4()
    files = BackupStorage()
    taken = files.directory(application_id) / "web-1-20261001-120000Z.dbs"
    taken.write_bytes(b"the good backup")

    with files.receiving(application_id) as incoming:
        incoming.write(b"a newer arrival")
        kept = files.install(incoming, application_id, taken.name)

    assert kept.relative_path == f"{application_id}/web-1-20261001-120000Z-2.dbs"
    assert taken.read_bytes() == b"the good backup"


def test_a_file_that_is_not_installed_leaves_nothing_behind(storage):
    application_id = uuid4()
    files = BackupStorage()

    with pytest.raises(RuntimeError):
        with files.receiving(application_id) as incoming:
            incoming.write(b"half")
            raise RuntimeError("the connection went away")

    assert os.listdir(files.directory(application_id)) == []


def test_only_partial_files_left_for_an_hour_are_swept(storage):
    application_id = uuid4()
    files = BackupStorage()
    directory = files.directory(application_id)
    old = (datetime.now(dt_timezone.utc) - timedelta(hours=2)).timestamp()
    stale = directory / ".incoming-0123456789abcdef.part"
    sealed = directory / "media.tar.gz.sealed.part"
    fresh = directory / ".incoming-fedcba9876543210.part"
    backup = directory / "web-1-20261001-120000Z.dbs"
    for path in (stale, sealed, fresh, backup):
        path.write_bytes(b"x")
    for path in (stale, sealed, backup):
        os.utime(path, (old, old))

    removed = files.sweep_partials(application_id)

    assert removed == sorted([stale.name, sealed.name])
    assert sorted(os.listdir(directory)) == sorted([fresh.name, backup.name])


def test_a_stored_file_is_read_checked_and_removed(storage):
    directory = BackupStorage().directory(uuid4())
    (directory / "a.dbs").write_bytes(b"content")
    relative = f"{directory.name}/a.dbs"
    files = BackupStorage()

    with files.open_read(relative) as handle:
        assert handle.read() == b"content"
    assert files.exists(relative)
    files.remove(relative)
    assert not files.exists(relative)
    files.remove(relative)
    with pytest.raises(FileNotFoundError):
        files.open_read(relative)


@pytest.mark.parametrize(
    "relative", ["", "/etc/passwd", "../outside.dbs", "a/../../b", "a\x00b"]
)
def test_a_path_that_leaves_the_root_is_refused(storage, relative):
    files = BackupStorage()

    for use in (files.open_read, files.exists, files.remove):
        with pytest.raises(ValueError):
            use(relative)


def test_a_sealed_file_takes_its_name_or_the_first_numbered_one_free(storage):
    application_id = uuid4()
    files = BackupStorage()
    directory = files.directory(application_id)

    first = files.unused_sealed_path(application_id, "db.sql.gz")
    (directory / "db.sql.gz.sealed").write_bytes(b"x")
    second = files.unused_sealed_path(application_id, "db.sql.gz")
    (directory / "db.sql.gz-2.sealed").write_bytes(b"x")
    third = files.unused_sealed_path(application_id, "db.sql.gz")

    assert first == f"{application_id}/db.sql.gz.sealed"
    assert second == f"{application_id}/db.sql.gz-2.sealed"
    assert third == f"{application_id}/db.sql.gz-3.sealed"


@pytest.mark.parametrize(
    "name", ["x" * 255, "x" + "نسخة" * 63], ids=["latin", "arabic"]
)
def test_a_name_too_long_for_this_disk_is_cut_where_a_character_ends(storage, name):
    application_id = uuid4()
    files = BackupStorage()
    files.directory(application_id)

    relative = files.unused_sealed_path(application_id, name)

    with files.writing(relative) as target:
        target.write(b"sealed")
    stored = relative.split("/", 1)[1]
    assert name.startswith(stored.removesuffix(".sealed"))
    assert len(f"{stored}-99.part".encode()) <= 255
    assert files.exists(relative)


def test_a_name_being_written_is_not_free_and_a_second_writer_is_refused(storage):
    application_id = uuid4()
    files = BackupStorage()
    files.directory(application_id)
    relative = files.unused_sealed_path(application_id, "db.sql.gz")

    with files.writing(relative) as target:
        target.write(b"first")
        assert (
            files.unused_sealed_path(application_id, "db.sql.gz")
            == f"{application_id}/db.sql.gz-2.sealed"
        )
        with pytest.raises(FileExistsError), files.writing(relative):
            pass

    with files.open_read(relative) as handle:
        assert handle.read() == b"first"
    with pytest.raises(FileExistsError), files.writing(relative):
        pass
    with files.open_read(relative) as handle:
        assert handle.read() == b"first"


def test_a_write_that_fails_leaves_neither_the_file_nor_its_part(storage):
    application_id = uuid4()
    files = BackupStorage()
    directory = files.directory(application_id)

    with (
        pytest.raises(RuntimeError),
        files.writing(f"{application_id}/db.sql.gz.sealed") as target,
    ):
        target.write(b"half")
        raise RuntimeError

    assert list(directory.iterdir()) == []


def test_the_uploads_directory_is_private_whatever_the_umask(storage, permissive_umask):
    uploads = BackupStorage().uploads_directory()

    assert uploads == storage / ".uploads"
    assert mode(uploads) == 0o700
    assert mode(storage) == 0o700


def test_only_uploads_untouched_since_the_cutoff_are_removed(storage):
    uploads = BackupStorage().uploads_directory()
    cutoff = datetime(2026, 10, 1, 12, 0, tzinfo=dt_timezone.utc)
    stale, fresh = uploads / "stale.upload", uploads / "fresh.upload"
    for path, moment in ((stale, cutoff - timedelta(seconds=1)), (fresh, cutoff)):
        path.write_bytes(b"plaintext")
        os.utime(path, (moment.timestamp(), moment.timestamp()))

    BackupStorage().remove_stale_uploads(before=cutoff)

    assert sorted(path.name for path in uploads.iterdir()) == ["fresh.upload"]


def test_no_uploads_directory_is_nothing_to_remove(storage):
    BackupStorage().remove_stale_uploads(
        before=datetime(2026, 10, 1, tzinfo=dt_timezone.utc)
    )

    assert not (storage / ".uploads").exists()
