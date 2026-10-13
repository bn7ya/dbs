import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import textwrap
import time
from datetime import datetime, timezone

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from dbs import audit, validate_backup
from dbs.models import AuditEvent, BackupRecord
from dbs.naming import backup_filename, is_backup_name
from dbs.tee import (
    PARTIAL_STALE_SECONDS,
    TeeSink,
    install_backup,
    is_partial_name,
    partial_name,
    sweep_partials,
)
from tests.testapp.models import Author

PASS = "stream-pass-phrase"
MOMENT = datetime(2026, 10, 13, 9, 30, 0, tzinfo=timezone.utc)


class Receiver(io.RawIOBase):
    def __init__(self, breaks_after=None, error=BrokenPipeError):
        self.received = bytearray()
        self.breaks_after = breaks_after
        self.error = error
        self.writes = 0

    def writable(self):
        return True

    def write(self, data):
        if self.breaks_after is not None and len(self.received) >= self.breaks_after:
            raise self.error(32, "Broken pipe")
        self.writes += 1
        self.received += bytes(data)
        return len(data)


class BinaryStdout:
    def __init__(self, buffer):
        self.buffer = buffer
        self.text = io.StringIO()

    def write(self, text):
        self.text.write(text)

    def flush(self):
        pass

    def isatty(self):
        return False


def names_in(directory):
    return sorted(os.listdir(directory))


def stream_command(tmp_path, receiver, *arguments, **options):
    stderr = io.StringIO()
    call_command(
        "dbs_backup",
        "--stream",
        *arguments,
        passphrase=PASS,
        kdf_time=1,
        kdf_memory=8192,
        stdout=BinaryStdout(receiver),
        stderr=stderr,
        **options,
    )
    return stderr.getvalue().splitlines()


def test_the_sink_sends_every_byte_and_keeps_the_same_bytes_under_a_backup_name(tmp_path):
    receiver = Receiver()
    data = os.urandom(3 * 1024 * 1024 + 17)

    with TeeSink(receiver, str(tmp_path), "web", moment=MOMENT) as sink:
        sink.write_all(data, chunk_size=1024 * 1024)
        kept = sink.finish()

    assert bytes(receiver.received) == data
    assert receiver.writes == 4
    assert kept.name == backup_filename("web", MOMENT)
    assert names_in(tmp_path) == [kept.name]
    stored = tmp_path / kept.name
    assert stored.read_bytes() == data
    assert stat.S_IMODE(stored.stat().st_mode) == 0o600
    assert kept.size == len(data)
    assert kept.sha256 == hashlib.sha256(data).hexdigest()
    assert kept.stream_lost is False
    assert kept.as_dict() == {"name": kept.name, "size": len(data), "sha256": kept.sha256}


def test_the_sink_takes_writes_one_at_a_time(tmp_path):
    receiver = Receiver()

    with TeeSink(receiver, str(tmp_path), "web", moment=MOMENT) as sink:
        for piece in (b"first ", b"second ", b"third"):
            sink.write(piece)
        kept = sink.finish()

    assert bytes(receiver.received) == b"first second third"
    assert (tmp_path / kept.name).read_bytes() == b"first second third"


@pytest.mark.parametrize("error", [BrokenPipeError, ConnectionResetError, OSError])
def test_a_stream_that_breaks_leaves_the_whole_backup_on_disk(tmp_path, error):
    receiver = Receiver(breaks_after=1024, error=error)
    data = os.urandom(10 * 1024)

    with TeeSink(receiver, str(tmp_path), "web", moment=MOMENT) as sink:
        sink.write_all(data, chunk_size=1024)
        kept = sink.finish()

    assert len(receiver.received) == 1024
    assert (tmp_path / kept.name).read_bytes() == data
    assert kept.stream_lost is True
    assert kept.as_dict()["kept_on_server"] is True
    assert kept.sha256 == hashlib.sha256(data).hexdigest()


def test_a_stream_already_closed_counts_as_lost(tmp_path):
    receiver = io.BytesIO()
    receiver.close()

    with TeeSink(receiver, str(tmp_path), "web", moment=MOMENT) as sink:
        sink.write_all(b"payload")
        kept = sink.finish()

    assert kept.stream_lost is True
    assert (tmp_path / kept.name).read_bytes() == b"payload"


def test_an_existing_backup_is_never_overwritten(tmp_path):
    taken = tmp_path / backup_filename("web", MOMENT)
    taken.write_bytes(b"the earlier backup")

    with TeeSink(Receiver(), str(tmp_path), "web", moment=MOMENT) as sink:
        sink.write_all(b"the new backup")
        kept = sink.finish()

    assert kept.name == backup_filename("web", MOMENT, ordinal=2)
    assert taken.read_bytes() == b"the earlier backup"
    assert (tmp_path / kept.name).read_bytes() == b"the new backup"


def test_install_refuses_once_every_name_is_taken(tmp_path, monkeypatch):
    monkeypatch.setattr("dbs.tee.MAX_ORDINAL", 2)
    for ordinal in (1, 2):
        (tmp_path / backup_filename("web", MOMENT, ordinal)).write_bytes(b"x")
    partial = tmp_path / partial_name("web")
    partial.write_bytes(b"y")

    with pytest.raises(Exception, match="unused backup filename"):
        install_backup(str(partial), str(tmp_path), "web", MOMENT)

    assert partial.read_bytes() == b"y"


def test_a_failure_while_writing_leaves_nothing_behind(tmp_path):
    with pytest.raises(RuntimeError):
        with TeeSink(Receiver(), str(tmp_path), "web", moment=MOMENT) as sink:
            sink.write(b"half a backup")
            raise RuntimeError("the database went away")

    assert names_in(tmp_path) == []


def test_partial_names_are_recognised():
    made = partial_name("web-20261013-093000Z.dbs")

    assert made.startswith(".web-20261013-093000Z.dbs.part-")
    assert is_partial_name(made)
    assert is_partial_name("web-20261013-093000Z.dbs.part")
    assert not is_partial_name("web-20261013-093000Z.dbs")
    assert not is_partial_name("notes.part")
    assert not is_partial_name(".notes.part-xyz")


def test_only_stale_partials_are_swept(tmp_path):
    stale = tmp_path / partial_name("web-20261013-093000Z.dbs")
    legacy = tmp_path / "web-20261013-093000Z.dbs.part"
    fresh = tmp_path / partial_name("web-20261013-093001Z.dbs")
    unrelated = tmp_path / "notes.part"
    backup = tmp_path / "web-20261013-093000Z.dbs"
    for path in (stale, legacy, fresh, unrelated, backup):
        path.write_bytes(b"x")
    old = time.time() - PARTIAL_STALE_SECONDS - 60
    for path in (stale, legacy, unrelated, backup):
        os.utime(path, (old, old))

    removed = sweep_partials(str(tmp_path))

    assert removed == sorted([stale.name, legacy.name])
    assert names_in(tmp_path) == sorted([fresh.name, unrelated.name, backup.name])


def test_sweeping_a_folder_that_is_not_there_removes_nothing(tmp_path):
    assert sweep_partials(str(tmp_path / "missing")) == []


@pytest.mark.django_db
def test_a_streamed_backup_goes_to_stdout_and_stays_on_the_server(tmp_path):
    Author.objects.create(name="Lovelace")
    receiver = Receiver()

    lines = stream_command(
        tmp_path, receiver, "--prefix", "web-1", "--output-dir", str(tmp_path / "kept")
    )

    summary = json.loads(lines[-1])
    assert set(summary) == {"name", "size", "sha256"}
    assert is_backup_name(summary["name"], "web-1")
    stored = tmp_path / "kept" / summary["name"]
    assert stored.read_bytes() == bytes(receiver.received)
    assert summary["size"] == len(receiver.received)
    assert summary["sha256"] == hashlib.sha256(receiver.received).hexdigest()
    result = validate_backup(bytes(receiver.received), PASS)
    assert result.ok and result.decrypted_ok
    assert names_in(tmp_path / "kept") == [summary["name"]]
    assert any("Streamed" in line for line in lines)
    record = BackupRecord.objects.get()
    assert record.filename == summary["name"]
    assert record.sha256 == summary["sha256"]
    event = AuditEvent.objects.get(action="backup.create")
    assert event.status == audit.SUCCEEDED
    assert event.target_name == summary["name"]
    assert event.data["streamed"] is True
    assert "kept_on_server" not in event.data


@pytest.mark.django_db
def test_a_stdout_that_breaks_still_finishes_the_backup_on_the_server(tmp_path):
    receiver = Receiver(breaks_after=0)

    lines = stream_command(tmp_path, receiver, output_dir=str(tmp_path))

    summary = json.loads(lines[-1])
    assert summary["kept_on_server"] is True
    assert receiver.received == bytearray()
    stored = tmp_path / summary["name"]
    data = stored.read_bytes()
    assert len(data) == summary["size"]
    assert hashlib.sha256(data).hexdigest() == summary["sha256"]
    assert validate_backup(data, PASS).decrypted_ok
    assert is_backup_name(summary["name"], "backup")
    assert any("kept on this server" in line for line in lines)
    assert AuditEvent.objects.get(action="backup.create").data["kept_on_server"] is True


@pytest.mark.django_db
def test_the_copy_lands_in_dbs_backup_dir_with_its_prefix(tmp_path, settings):
    settings.DBS_BACKUP_DIR = str(tmp_path / "backups")
    settings.DBS_BACKUP_PREFIX = "shop"

    lines = stream_command(tmp_path, Receiver())

    name = json.loads(lines[-1])["name"]
    assert is_backup_name(name, "shop")
    assert names_in(tmp_path / "backups") == [name]


@pytest.mark.django_db
def test_stale_partials_are_swept_before_a_stream(tmp_path):
    stale = tmp_path / partial_name("web-20261013-093000Z.dbs")
    stale.write_bytes(b"left by a crash")
    old = time.time() - PARTIAL_STALE_SECONDS - 60
    os.utime(stale, (old, old))

    stream_command(tmp_path, Receiver(), output_dir=str(tmp_path))

    assert not stale.exists()


@pytest.mark.django_db
def test_a_stream_needs_a_folder_to_keep_its_copy(tmp_path, settings):
    settings.DBS_BACKUP_DIR = None

    with pytest.raises(CommandError, match="DBS_BACKUP_DIR"):
        stream_command(tmp_path, Receiver())


@pytest.mark.django_db
@pytest.mark.parametrize("prefix", ["a/b", ""])
def test_a_prefix_that_cannot_name_a_backup_is_refused(tmp_path, prefix, settings):
    settings.DBS_BACKUP_PREFIX = prefix or "backup"

    if prefix:
        with pytest.raises(CommandError, match="cannot start a backup filename"):
            stream_command(tmp_path, Receiver(), "--prefix", prefix, output_dir=str(tmp_path))
    else:
        stream_command(tmp_path, Receiver(), "--prefix", prefix, output_dir=str(tmp_path))
        assert all(is_backup_name(name, "backup") for name in names_in(tmp_path))


@pytest.mark.django_db
def test_a_failed_backup_leaves_no_partial_and_records_the_failure(tmp_path, monkeypatch):
    from dbs.exceptions import DBSError

    def failing(*args, **kwargs):
        raise DBSError("the database went away")

    monkeypatch.setattr("dbs.management.commands.dbs_backup.create_backup", failing)

    with pytest.raises(CommandError, match="the database went away"):
        stream_command(tmp_path, Receiver(), output_dir=str(tmp_path))

    assert names_in(tmp_path) == []
    assert AuditEvent.objects.get(action="backup.create").status == audit.FAILED


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["--stream", "out.dbs"], "leave out the path"),
        (["out.dbs", "--prefix", "web"], "go with --stream"),
        (["--output-dir", "/tmp"], "go with --stream"),
        ([], "or use --stream"),
    ],
)
def test_stream_options_are_checked_before_anything_runs(arguments, message):
    with pytest.raises(CommandError, match=message):
        call_command("dbs_backup", *arguments, passphrase=PASS)


@pytest.mark.django_db
def test_stdout_that_takes_no_bytes_is_refused(tmp_path):
    with pytest.raises(CommandError, match="does not take bytes"):
        call_command(
            "dbs_backup",
            "--stream",
            passphrase=PASS,
            output_dir=str(tmp_path),
            stdout=io.StringIO(),
        )


@pytest.mark.django_db
def test_the_old_command_name_keeps_its_tip_off_the_stream(tmp_path):
    receiver = Receiver()
    stderr = io.StringIO()

    call_command(
        "django_dbs",
        "backup",
        "--stream",
        "--output-dir",
        str(tmp_path),
        passphrase=PASS,
        kdf_time=1,
        kdf_memory=8192,
        stdout=BinaryStdout(receiver),
        stderr=stderr,
    )

    assert "manage.py dbs" in stderr.getvalue()
    summary = json.loads(stderr.getvalue().splitlines()[-1])
    assert (tmp_path / summary["name"]).read_bytes() == bytes(receiver.received)


def test_a_process_whose_stdout_is_closed_exits_cleanly(tmp_path):
    script = textwrap.dedent(
        """
        import os, sys
        from dbs.tee import TeeSink
        from dbs.management.commands.dbs_backup import silence, surviving_a_lost_connection

        with surviving_a_lost_connection():
            with TeeSink(sys.stdout.buffer, sys.argv[1], "web") as sink:
                sink.write_all(os.urandom(8 * 1024 * 1024), chunk_size=64 * 1024)
                kept = sink.finish()
        if kept.stream_lost:
            silence(sys.stdout.buffer)
        sys.stderr.write("lost=%s size=%d\\n" % (kept.stream_lost, kept.size))
        """
    )
    environment = {**os.environ, "DJANGO_SETTINGS_MODULE": "tests.settings"}
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        cwd=os.getcwd(),
    )
    process.stdout.read(1024)
    process.stdout.close()
    error = process.stderr.read().decode()
    process.wait(timeout=60)

    assert process.returncode == 0, error
    assert "lost=True size=8388608" in error
    assert "Exception ignored" not in error
    [kept] = names_in(tmp_path)
    assert (tmp_path / kept).stat().st_size == 8 * 1024 * 1024
