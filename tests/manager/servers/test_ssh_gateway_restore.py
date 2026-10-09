from __future__ import annotations

import io
import os
import stat
import subprocess
from pathlib import Path

import pytest

from dbs.manager.servers.exceptions import (
    DbsTooOld,
    FileExists,
    RemoteCommandFailed,
    RestoreFailed,
)
from dbs.manager.servers.gateways import DbsProfile, RemoteHost
from dbs.transports import RemoteResult
from tests.manager.servers.support import (
    BACKUP_PASSPHRASE,
    SETTINGS_MODULE,
    LocalSftp,
)

BACKUP = b"DBS\x00 a django-dbs container, as far as this test is concerned"
DRY_RUN_OUTPUT = (
    "Flush would first delete 17 existing rows.\n"
    "Dry run: 42 records and 3 files would be restored; nothing was written.\n"
)

SERVER_PYTHON = """#!/bin/sh
record={record}
printf '%s\\n' "$@" > "$record/argv"
IFS= read -r line
printf '%s' "$line" > "$record/stdin"
printf '%s' "$DJANGO_SETTINGS_MODULE" > "$record/settings"
pwd > "$record/cwd"
cp "$3" "$record/sent"
stat -c %a "$3" > "$record/mode"
cat "$record/answer"
cat "$record/complaint" >&2
exit "$(cat "$record/status")"
"""


class ShellSession:
    def __init__(self) -> None:
        self.sftp = LocalSftp()
        self.commands: list[str] = []

    def run(self, command, *, stdin_line=None, timeout=None):
        self.commands.append(command)
        done = subprocess.run(
            ["/bin/sh", "-c", command],
            input=None if stdin_line is None else f"{stdin_line}\n",
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        return RemoteResult(done.returncode, done.stdout, done.stderr)

    def close(self) -> None:
        pass


class Server:
    def __init__(self, root: Path) -> None:
        self.record = root / "record"
        self.record.mkdir()
        self.project = root / "srv" / "app"
        self.project.mkdir(parents=True)
        self.backup_dir = root / "var" / "backups" / "dbs"
        python = root / "python"
        python.write_text(SERVER_PYTHON.format(record=self.record))
        python.chmod(0o755)
        self.python = str(python)
        self.answers(DRY_RUN_OUTPUT)

    def answers(self, stdout: str, *, stderr: str = "", status: int = 0) -> None:
        (self.record / "answer").write_text(stdout)
        (self.record / "complaint").write_text(stderr)
        (self.record / "status").write_text(str(status))

    def profile(self, settings_module: str | None = SETTINGS_MODULE) -> DbsProfile:
        return DbsProfile(
            python=self.python,
            manage="manage.py",
            project_dir=str(self.project),
            settings_module=settings_module,
        )

    def read(self, name: str) -> str:
        return (self.record / name).read_text()


@pytest.fixture
def server(tmp_path) -> Server:
    return Server(tmp_path)


def restore(server: Server, *, flush: bool, dry_run: bool, **options):
    remote = RemoteHost(options.pop("session", None) or ShellSession())
    return remote.restore_dbs_backup(
        io.BytesIO(BACKUP),
        profile=options.pop("profile", None) or server.profile(),
        passphrase=BACKUP_PASSPHRASE,
        remote_dir=str(server.backup_dir),
        flush=flush,
        dry_run=dry_run,
    )


def test_a_rehearsal_sends_the_file_runs_dbs_restore_and_reads_what_it_would_do(server):
    report = restore(server, flush=True, dry_run=True)

    [sent_as] = [
        line for line in server.read("argv").splitlines() if line.endswith(".dbs")
    ]
    assert server.read("argv").splitlines() == [
        "manage.py",
        "dbs_restore",
        sent_as,
        "--passphrase-stdin",
        "--flush",
        "--dry-run",
    ]
    assert Path(sent_as).parent == server.backup_dir
    assert Path(sent_as).name.startswith(".dbs-restore-")
    assert (server.record / "sent").read_bytes() == BACKUP
    assert server.read("mode").strip() == "600"
    assert server.read("stdin") == BACKUP_PASSPHRASE
    assert server.read("settings") == SETTINGS_MODULE
    assert server.read("cwd").strip() == os.path.realpath(server.project)
    assert (report.records, report.files, report.flushed, report.healed) == (
        42,
        3,
        17,
        False,
    )
    assert report.copy_left == ""


def test_the_copy_sent_is_removed_once_the_command_ends(server):
    restore(server, flush=False, dry_run=True)

    assert os.listdir(server.backup_dir) == []


def test_the_backup_folder_is_made_when_it_is_missing(server):
    assert not server.backup_dir.exists()

    restore(server, flush=False, dry_run=True)

    assert stat.S_IMODE(server.backup_dir.stat().st_mode) == 0o700


def test_the_passphrase_never_reaches_a_command_line(server):
    session = ShellSession()

    restore(server, flush=False, dry_run=False, session=session)

    assert all(BACKUP_PASSPHRASE not in command for command in session.commands)


def test_a_merge_for_real_passes_neither_option_and_reads_what_it_did(server):
    server.answers(
        "Merged into existing rows for shop.Order (use --flush to replace instead).\n"
        "Restored 12 records and 1 files.\n"
    )

    report = restore(server, flush=False, dry_run=False)

    assert server.read("argv").splitlines()[3:] == ["--passphrase-stdin"]
    assert (report.records, report.files, report.flushed) == (12, 1, None)


def test_a_replace_for_real_reads_the_rows_it_flushed(server):
    server.answers(
        "Flushed 9 existing rows from the backed-up models before loading.\n"
        "Restored 12 records and 0 files.\n"
    )

    report = restore(server, flush=True, dry_run=False)

    assert server.read("argv").splitlines()[3:] == ["--passphrase-stdin", "--flush"]
    assert (report.records, report.files, report.flushed) == (12, 0, 9)


def test_a_rehearsed_flush_that_clears_nothing_says_none(server):
    server.answers(
        "Dry run: 4 records and 0 files would be restored; nothing was written.\n"
    )

    report = restore(server, flush=True, dry_run=True)

    assert report.flushed == 0


def test_a_repaired_backup_is_reported(server):
    server.answers(
        "Corruption detected and repaired: 1 block repaired from parity.\n"
        "Restored 3 records and 0 files.\n"
    )

    assert restore(server, flush=False, dry_run=False).healed is True


def test_output_it_cannot_read_leaves_the_counts_unknown(server):
    server.answers("Something else entirely.\n")

    report = restore(server, flush=True, dry_run=True)

    assert (report.records, report.files, report.flushed) == (None, None, None)


def test_no_settings_module_exports_none(server):
    session = ShellSession()

    restore(
        server,
        flush=False,
        dry_run=True,
        session=session,
        profile=server.profile(settings_module=None),
    )

    assert all("DJANGO_SETTINGS_MODULE" not in command for command in session.commands)


def test_a_restore_that_fails_is_restore_failed_with_its_output_and_no_passphrase(
    server,
):
    server.answers(
        "",
        stderr=f"CommandError: Restore failed: wrong passphrase {BACKUP_PASSPHRASE}\n",
        status=1,
    )

    with pytest.raises(RestoreFailed) as raised:
        restore(server, flush=False, dry_run=False)

    assert "Restore failed" in raised.value.output
    assert BACKUP_PASSPHRASE not in raised.value.output
    assert os.listdir(server.backup_dir) == []


def test_a_server_whose_django_dbs_lacks_an_option_is_dbs_too_old(server):
    server.answers(
        "",
        stderr="manage.py dbs_restore: error: unrecognized arguments: --dry-run\n",
        status=2,
    )

    with pytest.raises(DbsTooOld) as raised:
        restore(server, flush=False, dry_run=True)

    assert "unrecognized arguments" in raised.value.output
    assert os.listdir(server.backup_dir) == []


def test_a_command_that_never_answers_still_has_its_copy_removed(server):
    class Dropping(ShellSession):
        def run(self, command, *, stdin_line=None, timeout=None):
            raise OSError("connection reset")

    with pytest.raises(RemoteCommandFailed):
        restore(server, flush=False, dry_run=True, session=Dropping())

    assert os.listdir(server.backup_dir) == []


def test_a_copy_that_cannot_be_removed_is_named_not_raised(server, monkeypatch):
    def refusing(self, path):
        raise RemoteCommandFailed(output=f"{path}: permission denied")

    monkeypatch.setattr(RemoteHost, "remove", refusing)

    report = restore(server, flush=False, dry_run=True)

    [left] = os.listdir(server.backup_dir)
    assert report.copy_left == str(server.backup_dir / left)
    assert report.records == 42


def test_a_name_that_is_taken_is_never_written_over(server, monkeypatch):
    server.backup_dir.mkdir(parents=True)
    taken = server.backup_dir / ".dbs-restore-0000000000000000.dbs"
    taken.write_bytes(b"someone else's")
    monkeypatch.setattr(
        "dbs.manager.servers.gateways.ssh_gateway.secrets.token_hex",
        lambda size: "0" * (2 * size),
    )

    with pytest.raises(FileExists):
        restore(server, flush=False, dry_run=True)

    assert taken.read_bytes() == b"someone else's"
    assert not (server.record / "argv").exists()
