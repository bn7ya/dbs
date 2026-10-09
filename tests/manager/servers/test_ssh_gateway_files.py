from __future__ import annotations

import os
import stat
from datetime import datetime
from datetime import timezone as dt_timezone
from io import BytesIO
from pathlib import Path

import pytest
from paramiko import SFTPAttributes, SSHException

from dbs.manager.servers.exceptions import (
    FileExists,
    FolderNotEmpty,
    RemoteCommandFailed,
    RemoteNotFound,
    RemotePermissionDenied,
)
from dbs.manager.servers.gateways import EntryKind, RemoteEntry, RemoteHost, ssh_gateway
from tests.manager.servers.support import LocalFile, LocalSftp, LocalSftpSession

MOMENT = 1_790_000_000


@pytest.fixture(autouse=True)
def umask():
    before = os.umask(0o022)
    yield
    os.umask(before)


@pytest.fixture
def remote() -> RemoteHost:
    return RemoteHost(LocalSftpSession())


def written(path: Path, content: bytes = b"content", mode: int = 0o640) -> Path:
    path.write_bytes(content)
    path.chmod(mode)
    os.utime(path, (MOMENT, MOMENT))
    return path


def refusing(error: Exception):
    def refuse(self, *args, **kwargs):
        raise error

    return refuse


def leftovers(folder: Path) -> list[str]:
    return sorted(name for name in os.listdir(folder) if ".part-" in name)


def test_a_path_resolves_through_every_link(remote, tmp_path):
    (tmp_path / "real").mkdir()
    (tmp_path / "alias").symlink_to(tmp_path / "real")

    assert remote.realpath(str(tmp_path / "alias")) == str(tmp_path / "real")
    assert remote.realpath(f"{tmp_path}/real/../alias/.") == str(tmp_path / "real")


def test_a_path_whose_last_part_alone_is_missing_still_resolves(remote, tmp_path):
    (tmp_path / "alias").symlink_to(tmp_path / "gone")

    assert remote.realpath(str(tmp_path / "new")) == str(tmp_path / "new")
    assert remote.realpath(str(tmp_path / "alias")) == str(tmp_path / "gone")


@pytest.mark.parametrize("relative", ["missing/new", "file/inside"])
def test_a_path_through_a_folder_that_is_not_there_is_remote_not_found(
    remote, tmp_path, relative
):
    written(tmp_path / "file")

    with pytest.raises(RemoteNotFound):
        remote.realpath(str(tmp_path / relative))


def test_a_loop_of_links_is_remote_not_found(remote, tmp_path):
    (tmp_path / "a").symlink_to(tmp_path / "b")
    (tmp_path / "b").symlink_to(tmp_path / "a")

    with pytest.raises(RemoteNotFound):
        remote.realpath(str(tmp_path / "a" / "x"))


@pytest.mark.parametrize(
    ("failure", "translated"),
    [
        (PermissionError(13, "Permission denied"), RemotePermissionDenied),
        (OSError("Failure"), RemoteCommandFailed),
        (SSHException("Server connection dropped"), RemoteCommandFailed),
        (
            UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
            RemoteCommandFailed,
        ),
    ],
)
def test_a_path_the_server_will_not_resolve_is_translated(
    monkeypatch, remote, tmp_path, failure, translated
):
    monkeypatch.setattr(LocalSftp, "normalize", refusing(failure))

    with pytest.raises(translated) as refused:
        remote.realpath(str(tmp_path))

    assert type(refused.value) is translated


def test_a_file_is_described_by_its_kind_size_time_and_permissions(remote, tmp_path):
    path = written(tmp_path / "logo.png", b"\x89PNG", 0o4750)

    assert remote.lstat(str(path)) == RemoteEntry(
        name="logo.png",
        path=str(path),
        kind=EntryKind.FILE,
        size=4,
        mtime=datetime.fromtimestamp(MOMENT, dt_timezone.utc),
        permissions=0o4750,
        uid=os.getuid(),
        gid=os.getgid(),
    )


def test_a_link_is_described_as_itself_wherever_it_points(remote, tmp_path):
    (tmp_path / "folder").mkdir()
    (tmp_path / "to-folder").symlink_to(tmp_path / "folder")
    (tmp_path / "dangling").symlink_to(tmp_path / "gone")

    for name in ("to-folder", "dangling"):
        entry = remote.lstat(str(tmp_path / name))
        assert (entry.kind, entry.size) == (EntryKind.LINK, None)


def test_a_folder_and_a_pipe_have_no_size(remote, tmp_path):
    (tmp_path / "folder").mkdir(mode=0o750)
    os.mkfifo(tmp_path / "pipe")

    folder = remote.lstat(str(tmp_path / "folder"))
    pipe = remote.lstat(str(tmp_path / "pipe"))

    assert (folder.kind, folder.size, folder.permissions) == (
        EntryKind.FOLDER,
        None,
        0o750,
    )
    assert (pipe.kind, pipe.size) == (EntryKind.OTHER, None)


def test_an_entry_the_server_sends_nothing_about_is_other(
    monkeypatch, remote, tmp_path
):
    monkeypatch.setattr(LocalSftp, "lstat", lambda self, path: SFTPAttributes())

    entry = remote.lstat(str(tmp_path / "x"))

    assert (entry.kind, entry.size, entry.mtime, entry.permissions) == (
        EntryKind.OTHER,
        None,
        None,
        None,
    )


def test_describing_a_path_that_is_not_there_is_remote_not_found(remote, tmp_path):
    with pytest.raises(RemoteNotFound):
        remote.lstat(str(tmp_path / "gone"))


def test_a_folder_lists_every_entry_as_itself(remote, tmp_path):
    written(tmp_path / "a.txt", b"abc")
    (tmp_path / "Docs").mkdir()
    (tmp_path / "docs-link").symlink_to(tmp_path / "Docs")
    (tmp_path / "escape").symlink_to("/etc")
    (tmp_path / ".hidden").write_bytes(b"")

    listed = {entry.name: entry for entry in remote.listdir(str(tmp_path))}

    assert {name: entry.kind for name, entry in listed.items()} == {
        "a.txt": EntryKind.FILE,
        "Docs": EntryKind.FOLDER,
        "docs-link": EntryKind.LINK,
        "escape": EntryKind.LINK,
        ".hidden": EntryKind.FILE,
    }
    assert listed["a.txt"].path == f"{tmp_path}/a.txt"
    assert listed["a.txt"].size == 3


@pytest.mark.parametrize("relative", ["gone", "a.txt"])
def test_listing_what_is_not_a_folder_is_remote_not_found(remote, tmp_path, relative):
    written(tmp_path / "a.txt")

    with pytest.raises(RemoteNotFound):
        remote.listdir(str(tmp_path / relative))


@pytest.mark.parametrize(
    ("failure", "translated"),
    [
        (PermissionError(13, "Permission denied"), RemotePermissionDenied),
        (
            UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
            RemoteCommandFailed,
        ),
        (EOFError(), RemoteCommandFailed),
    ],
)
def test_a_listing_the_server_refuses_is_translated(
    monkeypatch, remote, tmp_path, failure, translated
):
    monkeypatch.setattr(LocalSftp, "listdir_attr", refusing(failure))

    with pytest.raises(translated):
        remote.listdir(str(tmp_path))


def test_a_file_streams_in_windows_and_is_closed_after(monkeypatch, tmp_path):
    monkeypatch.setattr(ssh_gateway, "TRANSFER_WINDOW", 4)
    path = written(tmp_path / "x", b"0123456789")
    session = LocalSftpSession()

    with RemoteHost(session).stream_file(str(path)) as chunks:
        assert list(chunks) == [b"0123", b"4567", b"89"]

    [handle] = session.sftp.opened
    assert handle.closed
    assert not handle.prefetched


def test_a_stream_stops_at_its_limit_or_where_the_file_ends(
    monkeypatch, remote, tmp_path
):
    monkeypatch.setattr(ssh_gateway, "TRANSFER_WINDOW", 4)
    path = written(tmp_path / "x", b"0123456789")

    with remote.stream_file(str(path), 6) as chunks:
        assert list(chunks) == [b"0123", b"45"]
    with remote.stream_file(str(path), 100) as chunks:
        assert b"".join(chunks) == b"0123456789"
    with remote.stream_file(str(path), 0) as chunks:
        assert list(chunks) == []


def test_a_stream_is_closed_when_the_block_fails(tmp_path):
    path = written(tmp_path / "x")
    session = LocalSftpSession()

    with pytest.raises(ZeroDivisionError), RemoteHost(session).stream_file(str(path)):
        1 / 0

    assert session.sftp.opened[0].closed


def test_streaming_a_file_that_is_not_there_is_remote_not_found(remote, tmp_path):
    with pytest.raises(RemoteNotFound), remote.stream_file(str(tmp_path / "gone")):
        pass


@pytest.mark.parametrize(
    "failure", [SSHException("dropped"), OSError("Failure"), EOFError()]
)
def test_a_read_the_connection_fails_ends_the_stream(
    monkeypatch, remote, tmp_path, failure
):
    path = written(tmp_path / "x")
    monkeypatch.setattr(LocalFile, "readv", refusing(failure))

    with remote.stream_file(str(path)) as chunks, pytest.raises(RemoteCommandFailed):
        next(chunks)


def test_a_new_file_is_written_whole_and_takes_the_mode_of_a_new_file(remote, tmp_path):
    entry = remote.write_new(BytesIO(b"report"), str(tmp_path), "report.pdf")

    path = tmp_path / "report.pdf"
    assert path.read_bytes() == b"report"
    assert stat.S_IMODE(path.stat().st_mode) == 0o644
    assert (entry.name, entry.path, entry.kind, entry.size) == (
        "report.pdf",
        str(path),
        EntryKind.FILE,
        6,
    )
    assert leftovers(tmp_path) == []


def test_a_new_file_is_private_and_beside_its_name_while_it_is_written(
    remote, tmp_path
):
    seen = []

    class Watched(BytesIO):
        def read(self, size=-1):
            [partial] = leftovers(tmp_path)
            mode = stat.S_IMODE((tmp_path / partial).stat().st_mode)
            seen.append((partial, mode, (tmp_path / "a.txt").exists()))
            return super().read(size)

    remote.write_new(Watched(b"x" * 10), str(tmp_path), "a.txt")

    assert seen
    for partial, mode, named in seen:
        assert partial.startswith(".a.txt.part-")
        assert len(partial) == len(".a.txt.part-") + 16
        assert (mode, named) == (0o600, False)
    assert leftovers(tmp_path) == []


def test_an_empty_file_is_a_file(remote, tmp_path):
    entry = remote.write_new(BytesIO(b""), str(tmp_path), "__init__.py")

    assert (entry.kind, entry.size) == (EntryKind.FILE, 0)


def test_a_partial_file_of_a_long_name_still_fits_a_file_name(remote, tmp_path):
    name = "ن" * 127

    remote.write_new(BytesIO(b"x"), str(tmp_path), name)

    assert (tmp_path / name).read_bytes() == b"x"


@pytest.mark.parametrize("taken", ["file", "folder", "dangling-link"])
def test_a_name_that_is_taken_is_refused_before_a_byte_is_read(remote, tmp_path, taken):
    target = tmp_path / "a.txt"
    if taken == "file":
        written(target, b"original")
    elif taken == "folder":
        target.mkdir()
    else:
        target.symlink_to(tmp_path / "gone")
    source = BytesIO(b"new")

    with pytest.raises(FileExists) as refused:
        remote.write_new(source, str(tmp_path), "a.txt")

    assert (refused.value.status_code, refused.value.default_code) == (
        409,
        "file_exists",
    )
    assert source.tell() == 0
    assert leftovers(tmp_path) == []
    if taken == "file":
        assert target.read_bytes() == b"original"


def test_a_name_taken_while_the_file_was_written_is_never_replaced(
    monkeypatch, remote, tmp_path
):
    rename = LocalSftp.rename

    def beaten(self, old, new):
        Path(new).write_bytes(b"someone else's")
        rename(self, old, new)

    monkeypatch.setattr(LocalSftp, "rename", beaten)

    with pytest.raises(FileExists):
        remote.write_new(BytesIO(b"mine"), str(tmp_path), "a.txt")

    assert (tmp_path / "a.txt").read_bytes() == b"someone else's"
    assert leftovers(tmp_path) == []


def test_a_name_taken_right_before_the_rename_is_never_replaced(remote, tmp_path):
    class Racing(BytesIO):
        def read(self, size=-1):
            data = super().read(size)
            if not data:
                (tmp_path / "a.txt").write_bytes(b"someone else's")
            return data

    with pytest.raises(FileExists):
        remote.write_new(Racing(b"mine"), str(tmp_path), "a.txt")

    assert (tmp_path / "a.txt").read_bytes() == b"someone else's"
    assert leftovers(tmp_path) == []


def test_bytes_the_server_did_not_keep_fail_the_write_and_leave_nothing(
    monkeypatch, remote, tmp_path
):
    write = LocalFile.write
    monkeypatch.setattr(LocalFile, "write", lambda self, data: write(self, data[:-1]))

    with pytest.raises(RemoteCommandFailed) as failed:
        remote.write_new(BytesIO(b"report"), str(tmp_path), "a.txt")

    assert "the server kept 5 of 6 bytes" in failed.value.output
    assert os.listdir(tmp_path) == []


@pytest.mark.parametrize(
    ("failure", "translated"),
    [
        (PermissionError(13, "Permission denied"), RemotePermissionDenied),
        (OSError("Failure"), RemoteCommandFailed),
        (SSHException("dropped"), RemoteCommandFailed),
    ],
)
def test_a_write_that_fails_leaves_nothing(
    monkeypatch, remote, tmp_path, failure, translated
):
    monkeypatch.setattr(LocalFile, "write", refusing(failure))

    with pytest.raises(translated):
        remote.write_new(BytesIO(b"report"), str(tmp_path), "a.txt")

    assert os.listdir(tmp_path) == []


def test_a_rename_that_fails_otherwise_leaves_nothing(monkeypatch, remote, tmp_path):
    monkeypatch.setattr(LocalSftp, "rename", refusing(OSError("Failure")))

    with pytest.raises(RemoteCommandFailed):
        remote.write_new(BytesIO(b"report"), str(tmp_path), "a.txt")

    assert os.listdir(tmp_path) == []


def test_a_file_written_into_a_folder_that_is_not_there_is_remote_not_found(
    remote, tmp_path
):
    with pytest.raises(RemoteNotFound):
        remote.write_new(BytesIO(b"x"), str(tmp_path / "gone"), "a.txt")


def test_a_folder_the_user_may_not_write_to_is_remote_permission_denied(
    monkeypatch, remote, tmp_path
):
    monkeypatch.setattr(
        LocalSftp, "open", refusing(PermissionError(13, "Permission denied"))
    )

    with pytest.raises(RemotePermissionDenied):
        remote.write_new(BytesIO(b"x"), str(tmp_path), "a.txt")


@pytest.mark.parametrize("name", ["", ".", "..", "a/b", "/a"])
def test_a_new_file_is_named_with_one_file_name(remote, tmp_path, name):
    with pytest.raises(ValueError, match="Not a file name"):
        remote.write_new(BytesIO(b"x"), str(tmp_path), name)


def test_a_folder_is_made_with_the_mode_of_a_new_folder(remote, tmp_path):
    entry = remote.make_folder(str(tmp_path / "photos"))

    assert (tmp_path / "photos").is_dir()
    assert (entry.name, entry.kind, entry.permissions) == (
        "photos",
        EntryKind.FOLDER,
        0o755,
    )


@pytest.mark.parametrize("taken", ["file", "folder", "dangling-link"])
def test_a_folder_whose_name_is_taken_is_file_exists(remote, tmp_path, taken):
    target = tmp_path / "photos"
    if taken == "file":
        written(target)
    elif taken == "folder":
        target.mkdir()
    else:
        target.symlink_to(tmp_path / "gone")

    with pytest.raises(FileExists):
        remote.make_folder(str(target))


def test_a_folder_in_a_folder_that_is_not_there_is_remote_not_found(remote, tmp_path):
    with pytest.raises(RemoteNotFound):
        remote.make_folder(str(tmp_path / "gone" / "photos"))


def test_a_folder_the_server_refuses_otherwise_is_remote_command_failed(
    monkeypatch, remote, tmp_path
):
    monkeypatch.setattr(LocalSftp, "mkdir", refusing(OSError("Failure")))

    with pytest.raises(RemoteCommandFailed):
        remote.make_folder(str(tmp_path / "photos"))


def test_a_file_is_removed(remote, tmp_path):
    path = written(tmp_path / "a.txt")

    remote.remove_file(str(path))

    assert not path.exists()


def test_removing_a_link_removes_the_link_and_never_its_target(remote, tmp_path):
    target = written(tmp_path / "target.txt", b"kept")
    (tmp_path / "folder").mkdir()
    (tmp_path / "folder" / "inside").write_bytes(b"kept")
    (tmp_path / "file-link").symlink_to(target)
    (tmp_path / "folder-link").symlink_to(tmp_path / "folder")

    remote.remove_file(str(tmp_path / "file-link"))
    remote.remove_file(str(tmp_path / "folder-link"))

    assert sorted(os.listdir(tmp_path)) == ["folder", "target.txt"]
    assert target.read_bytes() == b"kept"
    assert (tmp_path / "folder" / "inside").read_bytes() == b"kept"


def test_removing_a_file_that_is_not_there_is_remote_not_found(remote, tmp_path):
    with pytest.raises(RemoteNotFound):
        remote.remove_file(str(tmp_path / "gone"))


def test_a_file_the_server_will_not_remove_is_remote_permission_denied(
    monkeypatch, remote, tmp_path
):
    path = written(tmp_path / "a.txt")
    monkeypatch.setattr(
        LocalSftp, "remove", refusing(PermissionError(13, "Permission denied"))
    )

    with pytest.raises(RemotePermissionDenied):
        remote.remove_file(str(path))

    assert path.exists()


def test_an_empty_folder_is_removed(remote, tmp_path):
    (tmp_path / "empty").mkdir()

    remote.remove_empty_folder(str(tmp_path / "empty"))

    assert not (tmp_path / "empty").exists()


def test_a_folder_that_holds_anything_is_never_removed(remote, tmp_path):
    folder = tmp_path / "full"
    folder.mkdir()
    (folder / ".hidden").write_bytes(b"kept")

    with pytest.raises(FolderNotEmpty) as refused:
        remote.remove_empty_folder(str(folder))

    assert (refused.value.status_code, refused.value.default_code) == (
        409,
        "folder_not_empty",
    )
    assert (folder / ".hidden").read_bytes() == b"kept"


def test_removing_a_folder_that_is_not_there_is_remote_not_found(remote, tmp_path):
    with pytest.raises(RemoteNotFound):
        remote.remove_empty_folder(str(tmp_path / "gone"))


def test_an_empty_folder_the_server_will_not_remove_is_remote_command_failed(
    monkeypatch, remote, tmp_path
):
    (tmp_path / "busy").mkdir()
    monkeypatch.setattr(LocalSftp, "rmdir", refusing(OSError("Failure")))

    with pytest.raises(RemoteCommandFailed):
        remote.remove_empty_folder(str(tmp_path / "busy"))


def test_a_name_the_server_will_not_let_be_looked_at_is_remote_permission_denied(
    monkeypatch, remote, tmp_path
):
    monkeypatch.setattr(
        LocalSftp, "lstat", refusing(PermissionError(13, "Permission denied"))
    )
    source = BytesIO(b"x")

    with pytest.raises(RemotePermissionDenied):
        remote.write_new(source, str(tmp_path), "a.txt")

    assert source.tell() == 0
    assert os.listdir(tmp_path) == []


def test_a_folder_that_fails_to_go_and_cannot_be_looked_into_says_why(
    monkeypatch, remote, tmp_path
):
    (tmp_path / "busy").mkdir()
    monkeypatch.setattr(LocalSftp, "rmdir", refusing(OSError("Failure")))
    monkeypatch.setattr(
        LocalSftp, "listdir_attr", refusing(PermissionError(13, "Permission denied"))
    )

    with pytest.raises(RemotePermissionDenied):
        remote.remove_empty_folder(str(tmp_path / "busy"))
