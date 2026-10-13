import os
import stat

import pytest

from dbs import io


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def names(directory):
    return sorted(path.name for path in directory.iterdir())


@pytest.fixture
def open_umask():
    previous = os.umask(0o000)
    yield
    os.umask(previous)


def test_a_new_file_is_private_from_the_first_byte(tmp_path, open_umask):
    seen = {}

    def verify(data):
        (partial,) = [path for path in tmp_path.iterdir() if path.name.endswith(".part")]
        seen["mode"] = mode(partial)
        seen["data"] = data

    written = io.write_new(b"payload", [str(tmp_path / "out.dbs")], verify)

    assert written == str(tmp_path / "out.dbs")
    assert seen == {"mode": 0o600, "data": b"payload"}
    assert mode(written) == 0o600
    assert names(tmp_path) == ["out.dbs"]


def test_a_taken_name_is_skipped_and_left_alone(tmp_path):
    taken = tmp_path / "out.dbs"
    taken.write_bytes(b"keep me")

    written = io.write_new(b"new", [str(taken), str(tmp_path / "out-2.dbs")])

    assert written == str(tmp_path / "out-2.dbs")
    assert taken.read_bytes() == b"keep me"
    assert (tmp_path / "out-2.dbs").read_bytes() == b"new"


def test_every_name_taken_writes_nothing(tmp_path):
    taken = tmp_path / "out.dbs"
    taken.write_bytes(b"keep me")

    with pytest.raises(FileExistsError):
        io.write_new(b"new", [str(taken)])

    assert names(tmp_path) == ["out.dbs"]
    assert taken.read_bytes() == b"keep me"


def test_a_rejected_file_never_takes_its_name(tmp_path):
    def reject(data):
        raise ValueError("does not validate")

    with pytest.raises(ValueError):
        io.write_new(b"broken", [str(tmp_path / "out.dbs")], reject)

    assert names(tmp_path) == []


def test_without_hard_links_the_name_is_still_claimed_exclusively(tmp_path, monkeypatch):
    def no_links(source, destination):
        raise PermissionError("links are not supported here")

    monkeypatch.setattr(io.os, "link", no_links)
    taken = tmp_path / "out.dbs"
    taken.write_bytes(b"keep me")

    written = io.write_new(b"new", [str(taken), str(tmp_path / "out-2.dbs")])

    assert taken.read_bytes() == b"keep me"
    assert (tmp_path / "out-2.dbs").read_bytes() == b"new"
    assert mode(written) == 0o600
    assert names(tmp_path) == ["out-2.dbs", "out.dbs"]
