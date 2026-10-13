import os
import signal
import socket
from contextlib import contextmanager
from io import StringIO

import pytest
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError

from dbs.engine import create_backup
from dbs.engine.restore import read_payload
from dbs.exceptions import MissingSourceFiles
from dbs.files import collect_root_files
from dbs.registry import BackupRegistry
from tests.conftest import FAST_KDF
from tests.testapp.dbs import BookBackup
from tests.testapp.models import Author, Book

PASS = "source-files-pass-phrase"

FAST = {"kdf_time": 1, "kdf_memory": 8192}

posix_only = pytest.mark.skipif(
    not hasattr(os, "mkfifo") or not hasattr(signal, "SIGALRM"),
    reason="needs FIFOs and SIGALRM",
)


def _books():
    registry = BackupRegistry()
    registry.register(Author)
    registry.register(Book)(BookBackup)
    return registry


@pytest.fixture
def ghost(db, tmp_path):
    author = Author.objects.create(name="Ada")
    return Book.objects.create(title="Ghost", author=author, sidecar_path=str(tmp_path / "gone.dat"))


@contextmanager
def deadline(seconds=5):
    def expire(signum, frame):
        raise TimeoutError("reading the source files hung")

    previous = signal.signal(signal.SIGALRM, expire)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def _collect(root):
    skipped = []
    with deadline():
        collected = list(collect_root_files(str(root), skipped))
    return {entry.name: data for entry, data in collected}, skipped


def test_a_missing_file_stops_the_backup_and_names_it(ghost, tmp_path):
    output = tmp_path / "never.dbs"

    with pytest.raises(MissingSourceFiles) as stopped:
        create_backup(PASS, registry=_books(), kdf_params=FAST_KDF, output=str(output))

    assert "gone.dat" in str(stopped.value)
    assert any("gone.dat" in item for item in stopped.value.files)
    assert not output.exists()


def test_allowing_missing_files_lists_them_in_the_backup(ghost):
    left_out = []

    container = create_backup(
        PASS,
        registry=_books(),
        kdf_params=FAST_KDF,
        allow_missing_files=True,
        skipped_files=left_out,
    )

    skipped = read_payload(container, PASS).document["stats"]["skipped_files"]
    assert any("gone.dat" in item and "missing" in item for item in skipped)
    assert left_out == skipped


@pytest.mark.parametrize("command", [("dbs_backup",), ("dbs", "backup")])
def test_the_command_fails_on_a_missing_file_unless_allowed(ghost, tmp_path, command):
    with pytest.raises(CommandError) as stopped:
        call_command(
            *command, str(tmp_path / "a.dbs"), passphrase=PASS, stdout=StringIO(), **FAST
        )
    assert "gone.dat" in str(stopped.value)
    assert "--allow-missing-files" in str(stopped.value)

    out = StringIO()
    call_command(
        *command,
        str(tmp_path / "b.dbs"),
        passphrase=PASS,
        allow_missing_files=True,
        stdout=out,
        **FAST,
    )
    assert "Left out 1 source file" in out.getvalue()
    assert "gone.dat" in out.getvalue()
    assert (tmp_path / "b.dbs").exists()


@posix_only
def test_a_fifo_in_a_root_is_skipped_without_hanging(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "plain.txt").write_bytes(b"plain")
    os.mkfifo(root / "pipe")

    collected, skipped = _collect(root)

    assert collected == {"plain.txt": b"plain"}
    assert skipped == [f"{root / 'pipe'} (not a regular file)"]


@posix_only
def test_a_socket_in_a_root_is_skipped(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        listener.bind(str(root / "s"))
        collected, skipped = _collect(root)
    finally:
        listener.close()

    assert collected == {}
    assert skipped == [f"{root / 's'} (not a regular file)"]


@posix_only
def test_a_symlink_out_of_a_root_is_never_followed(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_bytes(b"secret")
    (root / "inside.txt").write_bytes(b"inside")
    (root / "escape").symlink_to(outside)
    (root / "alias").symlink_to(root / "inside.txt")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "more.txt").write_bytes(b"more")
    (root / "folder").symlink_to(elsewhere, target_is_directory=True)

    collected, skipped = _collect(root)

    assert collected == {"inside.txt": b"inside", "alias": b"inside"}
    assert b"secret" not in collected.values()
    assert f"{root / 'escape'} (a symlink that leads outside its root)" in skipped
    assert f"{root / 'folder'} (a symlink that leads outside its root)" in skipped


@posix_only
@pytest.mark.django_db
def test_a_file_field_that_names_a_fifo_is_skipped_without_hanging(tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path / "media")
    author = Author.objects.create(name="Ada")
    book = Book.objects.create(title="Piped", author=author)
    book.cover.save("cover.bin", ContentFile(b"cover"), save=True)
    path = book.cover.path
    os.remove(path)
    os.mkfifo(path)
    left_out = []

    with deadline(10):
        create_backup(
            PASS,
            registry=_books(),
            kdf_params=FAST_KDF,
            allow_missing_files=True,
            skipped_files=left_out,
        )

    assert left_out == [f"testapp.book.cover: {book.cover.name} (not a regular file)"]


@pytest.mark.django_db
def test_a_file_field_symlinked_out_of_its_storage_is_skipped(tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path / "media")
    secret = tmp_path / "secret.bin"
    secret.write_bytes(b"secret")
    author = Author.objects.create(name="Ada")
    book = Book.objects.create(title="Linked", author=author)
    book.cover.save("cover.bin", ContentFile(b"cover"), save=True)
    os.remove(book.cover.path)
    os.symlink(secret, book.cover.path)
    left_out = []

    container = create_backup(
        PASS,
        registry=_books(),
        kdf_params=FAST_KDF,
        allow_missing_files=True,
        skipped_files=left_out,
    )

    assert left_out == [
        f"testapp.book.cover: {book.cover.name} (a symlink that leads outside its root)"
    ]
    assert read_payload(container, PASS).files == []
