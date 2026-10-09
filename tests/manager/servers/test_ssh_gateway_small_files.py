from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from paramiko import SSHException

from dbs.manager.servers.exceptions import (
    FileTooLarge,
    RemoteCommandFailed,
    RemoteNotFound,
    RemotePermissionDenied,
)
from dbs.manager.servers.gateways import EntryKind, RemoteHost
from tests.manager.servers.support import LocalFile, LocalSftp, LocalSftpSession


@pytest.fixture(autouse=True)
def umask():
    before = os.umask(0o022)
    yield
    os.umask(before)


@pytest.fixture
def session() -> LocalSftpSession:
    return LocalSftpSession()


@pytest.fixture
def remote(session) -> RemoteHost:
    return RemoteHost(session)


def written(path: Path, content: bytes = b"A=1\n", mode: int = 0o640) -> Path:
    path.write_bytes(content)
    path.chmod(mode)
    return path


def refusing(error: Exception):
    def refuse(self, *args, **kwargs):
        raise error

    return refuse


def leftovers(folder: Path) -> list[str]:
    return sorted(name for name in os.listdir(folder) if ".part-" in name)


def test_a_small_file_is_read_whole_and_closed(remote, session, tmp_path):
    path = written(tmp_path / ".env", b"SECRET_KEY=abc\nDEBUG=0\n")

    assert remote.read_small(str(path), 1024) == b"SECRET_KEY=abc\nDEBUG=0\n"
    [handle] = session.sftp.opened
    assert handle.closed


def test_an_empty_file_reads_as_nothing(remote, tmp_path):
    assert remote.read_small(str(written(tmp_path / ".env", b"")), 10) == b""


def test_a_link_is_followed_to_the_file(remote, tmp_path):
    written(tmp_path / "shared.env", b"A=1\n")
    (tmp_path / ".env").symlink_to(tmp_path / "shared.env")

    assert remote.read_small(str(tmp_path / ".env"), 10) == b"A=1\n"


def test_a_file_of_exactly_the_limit_is_read(remote, tmp_path):
    path = written(tmp_path / ".env", b"x" * 10)

    assert remote.read_small(str(path), 10) == b"x" * 10


def test_a_file_over_the_limit_is_refused_before_it_is_opened(
    remote, session, tmp_path
):
    path = written(tmp_path / ".env", b"x" * 11)

    with pytest.raises(FileTooLarge) as refused:
        remote.read_small(str(path), 10)

    assert (refused.value.status_code, refused.value.default_code) == (
        413,
        "file_too_large",
    )
    assert session.sftp.opened == []


def test_a_file_that_grew_after_its_size_was_read_is_refused_after_one_byte_more(
    monkeypatch, remote, session, tmp_path
):
    path = written(tmp_path / ".env", b"x" * 100)
    stat_of = LocalSftp.stat

    def smaller(self, at):
        answer = stat_of(self, at)
        answer.st_size = 5
        return answer

    reads = []
    read = LocalFile.read

    def counted(self, size=-1):
        reads.append(size)
        return read(self, size)

    monkeypatch.setattr(LocalSftp, "stat", smaller)
    monkeypatch.setattr(LocalFile, "read", counted)

    with pytest.raises(FileTooLarge):
        remote.read_small(str(path), 10)

    assert reads == [11]
    assert session.sftp.opened[0].closed


@pytest.mark.parametrize("kind", ["folder", "pipe"])
def test_what_is_not_a_regular_file_is_never_opened(remote, session, tmp_path, kind):
    path = tmp_path / ".env"
    if kind == "folder":
        path.mkdir()
    else:
        os.mkfifo(path)

    with pytest.raises(RemoteNotFound):
        remote.read_small(str(path), 10)

    assert session.sftp.opened == []


def test_a_file_that_is_not_there_is_remote_not_found(remote, tmp_path):
    with pytest.raises(RemoteNotFound):
        remote.read_small(str(tmp_path / ".env"), 10)


def test_a_file_the_user_may_not_read_is_remote_permission_denied(
    monkeypatch, remote, tmp_path
):
    path = written(tmp_path / ".env")
    monkeypatch.setattr(
        LocalSftp, "open", refusing(PermissionError(13, "Permission denied"))
    )

    with pytest.raises(RemotePermissionDenied):
        remote.read_small(str(path), 10)


def test_a_read_the_connection_fails_is_remote_command_failed(
    monkeypatch, remote, session, tmp_path
):
    path = written(tmp_path / ".env")
    monkeypatch.setattr(LocalFile, "read", refusing(SSHException("dropped")))

    with pytest.raises(RemoteCommandFailed):
        remote.read_small(str(path), 10)

    assert session.sftp.opened[0].closed


def test_a_file_is_replaced_whole_with_the_mode_it_is_given(remote, tmp_path):
    path = written(tmp_path / ".env", b"OLD=1\n", 0o640)
    before = path.stat().st_ino

    entry = remote.replace_file(str(path), b"NEW=2\n", mode=0o640)

    assert path.read_bytes() == b"NEW=2\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert path.stat().st_ino != before
    assert (entry.path, entry.kind, entry.size, entry.permissions) == (
        str(path),
        EntryKind.FILE,
        6,
        0o640,
    )
    assert leftovers(tmp_path) == []


def test_a_file_that_is_not_there_is_created_with_the_mode_it_is_given(
    remote, tmp_path
):
    remote.replace_file(str(tmp_path / ".env"), b"A=1\n", mode=0o600)

    assert (tmp_path / ".env").read_bytes() == b"A=1\n"
    assert stat.S_IMODE((tmp_path / ".env").stat().st_mode) == 0o600


def test_the_old_file_stays_whole_and_the_new_one_private_until_the_rename(
    monkeypatch, remote, tmp_path
):
    path = written(tmp_path / ".env", b"OLD=1\n", 0o644)
    seen = []
    write = LocalFile.write

    def watched(self, data):
        [partial] = leftovers(tmp_path)
        mode = stat.S_IMODE((tmp_path / partial).stat().st_mode)
        seen.append((partial, mode, path.read_bytes()))
        write(self, data)

    monkeypatch.setattr(LocalFile, "write", watched)

    remote.replace_file(str(path), b"NEW=2\n", mode=0o644)

    assert seen
    for partial, mode, current in seen:
        assert partial.startswith("..env.part-")
        assert (mode, current) == (0o600, b"OLD=1\n")
    assert path.read_bytes() == b"NEW=2\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o644


def test_an_owner_already_the_new_files_is_not_set_again(monkeypatch, remote, tmp_path):
    calls = []
    monkeypatch.setattr(
        LocalFile, "chown", lambda self, uid, gid: calls.append((uid, gid))
    )

    remote.replace_file(
        str(tmp_path / ".env"), b"A=1\n", mode=0o600, owner=(os.getuid(), os.getgid())
    )

    assert calls == []


def test_another_owner_is_given_to_the_file_before_the_rename(
    monkeypatch, remote, tmp_path
):
    path = written(tmp_path / ".env", b"OLD=1\n")
    calls = []

    def chown(self, uid, gid):
        calls.append((uid, gid, path.read_bytes()))

    monkeypatch.setattr(LocalFile, "chown", chown)

    remote.replace_file(str(path), b"NEW=2\n", mode=0o640, owner=(4242, 4343))

    assert calls == [(4242, 4343, b"OLD=1\n")]


def test_an_owner_the_server_will_not_give_leaves_the_file_as_it_was(
    monkeypatch, remote, tmp_path
):
    path = written(tmp_path / ".env", b"OLD=1\n", 0o640)
    monkeypatch.setattr(
        LocalFile, "chown", refusing(PermissionError(1, "Operation not permitted"))
    )

    with pytest.raises(RemotePermissionDenied):
        remote.replace_file(str(path), b"NEW=2\n", mode=0o640, owner=(4242, 4343))

    assert path.read_bytes() == b"OLD=1\n"
    assert leftovers(tmp_path) == []


def test_a_link_at_the_path_is_replaced_and_its_target_left_alone(remote, tmp_path):
    target = written(tmp_path / "shared.env", b"OLD=1\n")
    (tmp_path / ".env").symlink_to(target)

    remote.replace_file(str(tmp_path / ".env"), b"NEW=2\n", mode=0o600)

    assert not (tmp_path / ".env").is_symlink()
    assert (tmp_path / ".env").read_bytes() == b"NEW=2\n"
    assert target.read_bytes() == b"OLD=1\n"


def test_a_rename_the_server_refuses_leaves_the_file_as_it_was(
    monkeypatch, remote, tmp_path
):
    path = written(tmp_path / ".env", b"OLD=1\n")
    monkeypatch.setattr(
        LocalSftp, "posix_rename", refusing(OSError("Operation unsupported"))
    )

    with pytest.raises(RemoteCommandFailed):
        remote.replace_file(str(path), b"NEW=2\n", mode=0o640)

    assert path.read_bytes() == b"OLD=1\n"
    assert leftovers(tmp_path) == []


def test_bytes_the_server_did_not_keep_leave_the_file_as_it_was(
    monkeypatch, remote, tmp_path
):
    path = written(tmp_path / ".env", b"OLD=1\n")
    write = LocalFile.write
    monkeypatch.setattr(LocalFile, "write", lambda self, data: write(self, data[:-1]))

    with pytest.raises(RemoteCommandFailed) as failed:
        remote.replace_file(str(path), b"NEW=2\n", mode=0o640)

    assert "the server kept 5 of 6 bytes" in failed.value.output
    assert path.read_bytes() == b"OLD=1\n"
    assert leftovers(tmp_path) == []


def test_a_folder_that_is_not_there_is_remote_not_found(remote, tmp_path):
    with pytest.raises(RemoteNotFound):
        remote.replace_file(str(tmp_path / "gone" / ".env"), b"A=1\n", mode=0o600)


def test_a_folder_the_user_may_not_write_to_is_remote_permission_denied(
    monkeypatch, remote, tmp_path
):
    monkeypatch.setattr(
        LocalSftp, "open", refusing(PermissionError(13, "Permission denied"))
    )

    with pytest.raises(RemotePermissionDenied):
        remote.replace_file(str(tmp_path / ".env"), b"A=1\n", mode=0o600)


@pytest.mark.parametrize(
    "path", ["", ".env", "relative/.env", "/srv/", "/srv/..", "/srv/."]
)
def test_only_an_absolute_file_path_is_replaced(remote, path):
    with pytest.raises(ValueError, match="Not an absolute file path"):
        remote.replace_file(path, b"A=1\n", mode=0o600)
