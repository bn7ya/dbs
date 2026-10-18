from __future__ import annotations

import base64
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from dbs.manager.servers.gateways.ssh_gateway import (
    MODE_OF,
    NOT_A_FILE_STATUS,
    READ_SMALL,
    RECEIVE_FILE,
    SWEEP_STALE,
    TOO_LARGE_STATUS,
)
from dbs.tee import partial_name

SHORT_STATUS = 5
AN_HOUR_AND_A_BIT = 3600 + 60


def run(script: str, *arguments, data: bytes = b"") -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", script, *map(str, arguments)],
        input=data,
        capture_output=True,
        check=False,
        timeout=30,
    )


def mode_of(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def aged(path: Path, seconds: float) -> Path:
    moment = time.time() - seconds
    os.utime(path, (moment, moment), follow_symlinks=False)
    return path


@pytest.fixture(autouse=True)
def umask():
    previous = os.umask(0o022)
    yield
    os.umask(previous)


def test_a_small_file_is_read_whole_as_base64(tmp_path):
    secret = tmp_path / ".env"
    secret.write_bytes(b"SECRET_KEY=x\nDEBUG=0\n")

    done = run(READ_SMALL, secret, 1024)

    assert done.returncode == 0
    assert base64.b64decode(done.stdout) == b"SECRET_KEY=x\nDEBUG=0\n"


def test_a_file_of_exactly_the_limit_is_read_and_one_byte_more_is_too_large(tmp_path):
    secret = tmp_path / ".env"
    secret.write_bytes(b"A" * 64)

    exact = run(READ_SMALL, secret, 64)
    over = run(READ_SMALL, secret, 63)

    assert base64.b64decode(exact.stdout) == b"A" * 64
    assert over.returncode == TOO_LARGE_STATUS == 3
    assert over.stdout == b""


def test_an_empty_file_reads_as_nothing(tmp_path):
    empty = tmp_path / ".env"
    empty.write_bytes(b"")

    done = run(READ_SMALL, empty, 1024)

    assert (done.returncode, done.stdout) == (0, b"")


def test_a_link_is_followed_to_the_file_it_names(tmp_path):
    target = tmp_path / "real.env"
    target.write_bytes(b"A=1\n")
    (tmp_path / ".env").symlink_to(target)

    done = run(READ_SMALL, tmp_path / ".env", 1024)

    assert base64.b64decode(done.stdout) == b"A=1\n"


@pytest.mark.parametrize("kind", ["missing", "folder", "pipe", "dangling"])
def test_what_is_not_a_regular_file_is_never_read(tmp_path, kind):
    path = tmp_path / "thing"
    if kind == "folder":
        path.mkdir()
    elif kind == "pipe":
        os.mkfifo(path)
    elif kind == "dangling":
        path.symlink_to(tmp_path / "gone")

    done = run(READ_SMALL, path, 1024)

    assert done.returncode == NOT_A_FILE_STATUS == 4
    assert done.stdout == b""


def test_a_received_file_holds_exactly_the_bytes_sent_and_is_private(tmp_path):
    target = tmp_path / ".dbs-restore-0123456789abcdef.dbs"

    done = run(RECEIVE_FILE, target, 11, data=b"hello world")

    assert done.returncode == 0
    assert target.read_bytes() == b"hello world"
    assert mode_of(target) == 0o600


def test_a_receiver_stops_at_the_size_it_was_told(tmp_path):
    target = tmp_path / "received"

    done = run(RECEIVE_FILE, target, 5, data=b"hello and more")

    assert done.returncode == 0
    assert target.read_bytes() == b"hello"


def test_a_large_file_arrives_whole_across_many_reads(tmp_path):
    target = tmp_path / "received"
    data = os.urandom(3 * (1 << 20) + 17)

    done = run(RECEIVE_FILE, target, len(data), data=data)

    assert done.returncode == 0
    assert target.read_bytes() == data


@pytest.mark.parametrize("taken_by", ["file", "link", "dangling link"])
def test_a_name_that_is_taken_is_never_written_over(tmp_path, taken_by):
    other = tmp_path / "other"
    other.write_bytes(b"someone else's")
    target = tmp_path / "received"
    if taken_by == "file":
        target.write_bytes(b"someone else's")
    elif taken_by == "link":
        target.symlink_to(other)
    else:
        target.symlink_to(tmp_path / "gone")

    done = run(RECEIVE_FILE, target, 5, data=b"hello")

    assert done.returncode != 0
    assert b"FileExistsError" in done.stderr
    assert other.read_bytes() == b"someone else's"
    assert not (tmp_path / "gone").exists()
    if taken_by == "file":
        assert target.read_bytes() == b"someone else's"


def test_a_transfer_that_ends_early_exits_5_and_leaves_nothing(tmp_path):
    target = tmp_path / "received"

    done = run(RECEIVE_FILE, target, 100, data=b"only this")

    assert done.returncode == SHORT_STATUS
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_a_replacement_is_written_beside_the_file_then_renamed_over_it(tmp_path):
    target = tmp_path / ".env"
    target.write_bytes(b"OLD=1\n")
    target.chmod(0o640)
    before = target.stat().st_ino
    partial = tmp_path / partial_name(".env")

    done = run(RECEIVE_FILE, target, 6, "0o640", partial, data=b"NEW=2\n")

    assert done.returncode == 0
    assert target.read_bytes() == b"NEW=2\n"
    assert mode_of(target) == 0o640
    assert target.stat().st_ino != before
    assert not partial.exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == [".env"]


def test_a_replacement_that_ends_early_leaves_the_file_as_it_was(tmp_path):
    target = tmp_path / ".env"
    target.write_bytes(b"OLD=1\n")
    partial = tmp_path / partial_name(".env")

    done = run(RECEIVE_FILE, target, 100, "0o640", partial, data=b"NEW=2\n")

    assert done.returncode == SHORT_STATUS
    assert target.read_bytes() == b"OLD=1\n"
    assert not partial.exists()


def test_a_partial_name_that_is_taken_stops_the_replacement(tmp_path):
    target = tmp_path / ".env"
    target.write_bytes(b"OLD=1\n")
    partial = tmp_path / partial_name(".env")
    partial.write_bytes(b"in flight")

    done = run(RECEIVE_FILE, target, 6, "0o640", partial, data=b"NEW=2\n")

    assert done.returncode != 0
    assert target.read_bytes() == b"OLD=1\n"
    assert partial.read_bytes() == b"in flight"


def test_the_mode_of_a_file_is_printed_as_octal(tmp_path):
    target = tmp_path / ".env"
    target.write_bytes(b"A=1\n")
    target.chmod(0o640)

    done = run(MODE_OF, target)

    assert done.returncode == 0
    assert done.stdout.decode().strip() == "0o640"


def test_a_file_that_is_not_there_has_no_mode(tmp_path):
    done = run(MODE_OF, tmp_path / "gone")

    assert done.returncode == 0
    assert done.stdout.decode().strip() == ""


def test_a_mode_read_is_a_mode_the_receiver_takes(tmp_path):
    target = tmp_path / ".env"
    target.write_bytes(b"OLD=1\n")
    target.chmod(0o604)
    mode = run(MODE_OF, target).stdout.decode().strip()

    run(RECEIVE_FILE, target, 6, mode, tmp_path / partial_name(".env"), data=b"NEW=2\n")

    assert mode_of(target) == 0o604


def test_only_partials_and_restore_copies_left_for_an_hour_are_swept(tmp_path):
    stale_partial = aged(_written(tmp_path / partial_name(".env")), AN_HOUR_AND_A_BIT)
    stale_restore = aged(
        _written(tmp_path / ".dbs-restore-0123456789abcdef.dbs"), AN_HOUR_AND_A_BIT
    )
    fresh_partial = _written(tmp_path / partial_name("settings.env"))
    fresh_restore = _written(tmp_path / ".dbs-restore-fedcba9876543210.dbs")
    kept = [
        aged(_written(tmp_path / name), AN_HOUR_AND_A_BIT)
        for name in (
            ".env",
            "web-1.dbs",
            ".env.part-0123",
            ".dbs-restore-0123.dbs",
            "env.part-0123456789abcdef",
        )
    ]

    done = run(SWEEP_STALE, tmp_path)

    assert done.returncode == 0
    assert done.stdout.decode().strip() == "2"
    assert not stale_partial.exists() and not stale_restore.exists()
    assert fresh_partial.exists() and fresh_restore.exists()
    assert all(path.exists() for path in kept)


def test_a_link_or_folder_named_like_a_partial_is_never_swept(tmp_path):
    target = tmp_path / "kept.env"
    target.write_bytes(b"x")
    aged(target, AN_HOUR_AND_A_BIT)
    link = tmp_path / partial_name("link")
    link.symlink_to(target)
    aged(link, AN_HOUR_AND_A_BIT)
    folder = tmp_path / ".dbs-restore-0123456789abcdef.dbs"
    folder.mkdir()
    aged(folder, AN_HOUR_AND_A_BIT)

    done = run(SWEEP_STALE, tmp_path)

    assert done.stdout.decode().strip() == "0"
    assert link.is_symlink() and target.exists() and folder.is_dir()


def test_a_folder_that_cannot_be_listed_is_skipped_and_the_others_swept(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    stale = [
        aged(_written(folder / ".dbs-restore-0123456789abcdef.dbs"), AN_HOUR_AND_A_BIT)
        for folder in (first, second)
    ]

    done = run(SWEEP_STALE, tmp_path / "gone", first, tmp_path / "file", second)

    assert done.returncode == 0
    assert done.stdout.decode().strip() == "2"
    assert not any(path.exists() for path in stale)


def _written(path: Path) -> Path:
    path.write_bytes(b"x")
    return path
