from __future__ import annotations

import errno
import hashlib
import io
import json
import os
import re
import shlex
import stat
import subprocess
import tarfile
from datetime import datetime
from datetime import timezone as dt_timezone
from pathlib import Path

import pytest
from paramiko import SFTPAttributes, SSHException

from dbs.exceptions import ConfigurationError, DBSError, HostKeyError
from dbs.manager.servers.exceptions import (
    ArchiveFailed,
    DbsTooOld,
    HostKeyChanged,
    RemoteCommandFailed,
    RemoteNotFound,
    RemotePermissionDenied,
    SSHAuthFailed,
    SSHUnreachable,
    StreamBroken,
)
from dbs.manager.servers.gateways import (
    Credentials,
    DbsProfile,
    RemoteFile,
    RemoteHost,
    build_script,
    connect,
    fetch_host_key,
    parse_host_key,
)
from dbs.naming import backup_filename
from dbs.tee import partial_name
from dbs.transports import RemoteResult
from dbs.transports.ssh import StreamInterrupted
from tests.manager.servers.support import (
    BACKUP_DIR,
    BACKUP_PASSPHRASE,
    PROJECT_DIR,
    PYTHON,
    SETTINGS_MODULE,
    LocalSftp,
    host_key_line,
)


def run_locally(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["/bin/sh", "-c", script],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def hostile(canary) -> list[str]:
    return [
        f"'; touch {canary}; echo '",
        f"$(touch {canary})",
        f"`touch {canary}`",
        f"a  b; touch {canary}",
        f'" && touch {canary} && echo "',
    ]


def test_every_argument_reaches_the_command_as_itself(tmp_path):
    canary = tmp_path / "ran"
    values = hostile(canary)

    result = run_locally(build_script(["printf", "%s\\n", *values]))

    assert result.returncode == 0
    assert result.stdout.splitlines() == values
    assert not canary.exists()


def test_environment_values_are_quoted(tmp_path):
    canary = tmp_path / "ran"
    value = hostile(canary)[1]

    result = run_locally(build_script(["printenv", "HOSTILE"], env={"HOSTILE": value}))

    assert result.stdout == value + "\n"
    assert not canary.exists()


def test_the_command_runs_in_the_directory_it_names(tmp_path):
    directory = tmp_path / "it's $(here)"
    directory.mkdir()

    result = run_locally(build_script(["pwd"], cwd=str(directory)))

    assert result.stdout.strip() == os.path.realpath(directory)


def test_a_directory_that_is_missing_stops_the_command(tmp_path):
    canary = tmp_path / "ran"

    result = run_locally(
        build_script(["touch", str(canary)], cwd=str(tmp_path / "missing"))
    )

    assert result.returncode != 0
    assert not canary.exists()


def test_the_script_is_one_quoted_argument_to_sh():
    script = build_script(
        ["echo", "'; rm -rf /"], cwd="/srv/$(reboot)", env={"X": "$(id)"}
    )

    program, flag, body = shlex.split(script)

    assert (program, flag) == ("/bin/sh", "-c")
    assert body.splitlines() == [
        "cd '/srv/$(reboot)' || exit 1",
        "export X='$(id)'",
        "exec echo ''\"'\"'; rm -rf /'",
    ]


@pytest.mark.parametrize("name", ["BAD-NAME", "1X", "X;rm -rf /", "X Y", "$(id)", ""])
def test_an_environment_name_that_is_not_one_is_refused(name):
    with pytest.raises(ValueError, match="Not an environment variable name"):
        build_script(["true"], env={name: "value"})


def test_a_host_key_line_is_parsed_and_normalised():
    line = host_key_line()

    key = parse_host_key(f"  {line}  root@web-1 ")

    assert key.line == line
    assert key.key_type == "ssh-ed25519"
    assert key.fingerprint.startswith("SHA256:")


@pytest.mark.parametrize(
    "line",
    [
        "",
        "ssh-ed25519",
        "ssh-ed25519 !!!!",
        "foo AAAAA2Zvbw==",
        "ssh-rsa AAAAC3NzaC1lZDI1NTE5",
    ],
)
def test_a_line_no_connection_could_pin_is_refused(line):
    with pytest.raises(ValueError, match="Not a host key"):
        parse_host_key(line)


def test_credentials_keep_their_secrets_out_of_repr():
    credentials = Credentials(
        host="10.0.0.5",
        port=22,
        username="deploy",
        host_key=host_key_line(),
        private_key="PRIVATE-KEY-BODY",
        key_passphrase="KEY-PASSPHRASE",
        password="SSH-PASSWORD",
    )

    shown = repr(credentials)

    assert "10.0.0.5" in shown
    for secret in ("PRIVATE-KEY-BODY", "KEY-PASSPHRASE", "SSH-PASSWORD"):
        assert secret not in shown


class FakeChannel:
    def __init__(self) -> None:
        self.timeout = None

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout


class FakeSftp:
    def __init__(self, paths: set[str], failure: Exception | None = None) -> None:
        self.paths = paths
        self.failure = failure
        self.channel = FakeChannel()

    def get_channel(self) -> FakeChannel:
        return self.channel

    def stat(self, path: str) -> object:
        if self.failure:
            raise self.failure
        if path not in self.paths:
            raise FileNotFoundError(path)
        return object()


class FakeSession:
    def __init__(
        self, *, sftp=None, failure: Exception | None = None, result=None
    ) -> None:
        self._sftp = sftp
        self.failure = failure
        self.result = result
        self.commands: list[tuple[str, str | None, float | None]] = []
        self.closed = False

    @property
    def sftp(self):
        if self.failure:
            raise self.failure
        return self._sftp

    def run(self, command, *, stdin_line=None, timeout=None):
        self.commands.append((command, stdin_line, timeout))
        if self.failure:
            raise self.failure
        return self.result

    def close(self) -> None:
        self.closed = True


TRANSPORT_FAILURES = [
    DBSError("timed out"),
    SSHException("SSH session not active"),
    OSError("connection reset"),
    EOFError(),
]


def test_a_command_is_sent_as_its_quoted_script_with_the_default_timeout(settings):
    session = FakeSession(result="done")

    result = RemoteHost(session).run(["echo", "a b"], cwd="/srv", stdin_line="secret")

    assert result == "done"
    assert session.commands == [
        (
            build_script(["echo", "a b"], cwd="/srv"),
            "secret",
            settings.SSH_COMMAND_TIMEOUT,
        )
    ]


@pytest.mark.parametrize("failure", TRANSPORT_FAILURES)
def test_a_transport_failure_during_a_command_is_remote_command_failed(failure):
    with pytest.raises(RemoteCommandFailed):
        RemoteHost(FakeSession(failure=failure)).run(["true"])


@pytest.mark.parametrize("failure", TRANSPORT_FAILURES)
def test_an_sftp_channel_that_will_not_open_is_remote_command_failed(failure):
    with pytest.raises(RemoteCommandFailed):
        RemoteHost(FakeSession(failure=failure)).exists("/srv")


def test_sftp_reads_are_bounded_by_the_io_timeout(settings):
    sftp = FakeSftp({"/srv"})

    opened = RemoteHost(FakeSession(sftp=sftp)).sftp

    assert opened is sftp
    assert sftp.channel.timeout == settings.SSH_IO_TIMEOUT


def test_a_path_exists_or_does_not():
    remote = RemoteHost(FakeSession(sftp=FakeSftp({"/srv/app"})))

    assert remote.exists("/srv/app") is True
    assert remote.exists("/srv/missing") is False


@pytest.mark.parametrize(
    "failure", [SSHException("Server connection dropped"), EOFError()]
)
def test_a_stat_on_a_dropped_channel_is_remote_command_failed(failure):
    remote = RemoteHost(FakeSession(sftp=FakeSftp({"/srv"}, failure=failure)))

    with pytest.raises(RemoteCommandFailed):
        remote.exists("/srv")


def credentials() -> Credentials:
    return Credentials(
        host="10.0.0.5",
        port=2222,
        username="deploy",
        host_key=host_key_line(),
        password="SSH-PASSWORD",
        remote_dir="/var/backups/dbs",
    )


@pytest.mark.parametrize(
    ("failure", "translated"),
    [
        (HostKeyError("mismatch"), HostKeyChanged),
        (ConfigurationError("authentication failed"), SSHAuthFailed),
        (DBSError("connection refused"), SSHUnreachable),
    ],
)
def test_a_connection_that_fails_is_translated(monkeypatch, failure, translated):
    class Refusing:
        def __init__(self, target, on_activity=None) -> None:
            pass

        def __enter__(self):
            raise failure

    monkeypatch.setattr("dbs.manager.servers.gateways.ssh_gateway.SSHSession", Refusing)

    with pytest.raises(translated), connect(credentials()):
        pass


def test_a_connection_trusts_only_the_pinned_key_and_is_closed_after(
    monkeypatch, settings
):
    opened = []

    class Recording(FakeSession):
        def __init__(self, target, on_activity=None) -> None:
            super().__init__()
            self.target = target
            opened.append(self)

        def __enter__(self):
            return self

    monkeypatch.setattr(
        "dbs.manager.servers.gateways.ssh_gateway.SSHSession", Recording
    )
    given = credentials()

    with connect(given) as remote:
        assert isinstance(remote, RemoteHost)
        assert not opened[0].closed

    target = opened[0].target
    assert opened[0].closed
    assert target.host_key == given.host_key
    assert (target.use_agent, target.auto_add_host_key) == (False, False)
    assert target.known_hosts is None
    assert target.connect_timeout == settings.SSH_CONNECT_TIMEOUT
    assert target.keepalive_interval == settings.SSH_KEEPALIVE_INTERVAL
    assert target.io_timeout == settings.SSH_IO_TIMEOUT
    assert target.remote_dir == given.remote_dir


def test_a_host_that_does_not_answer_has_no_host_key(monkeypatch, settings):
    asked = []

    def unreachable(host, port, *, timeout):
        asked.append((host, port, timeout))
        raise DBSError("Cannot reach")

    monkeypatch.setattr(
        "dbs.manager.servers.gateways.ssh_gateway.dbs_fetch_host_key", unreachable
    )

    with pytest.raises(SSHUnreachable):
        fetch_host_key("10.0.0.9", 22)
    assert asked == [("10.0.0.9", 22, settings.SSH_CONNECT_TIMEOUT)]


PROFILE = DbsProfile(
    python=PYTHON,
    manage="manage.py",
    project_dir=PROJECT_DIR,
    settings_module=SETTINGS_MODULE,
)
CONTENT = b"DBS container bytes" * 1000
DIGEST = hashlib.sha256(CONTENT).hexdigest()


def summary_line(name: str, **extra) -> str:
    return json.dumps({"name": name, "size": len(CONTENT), "sha256": DIGEST, **extra})


class StreamingSession(FakeSession):
    def __init__(self, *, sent=CONTENT, result=None, failure=None) -> None:
        super().__init__(sftp=LocalSftp())
        self.sent = sent
        self.answer = result
        self.raised = failure
        self.streams: list[dict] = []

    def stream(self, command, sink, *, stdin_line=None, timeout=None, progress=None):
        self.streams.append(
            {"command": command, "stdin": stdin_line, "timeout": timeout}
        )
        sink.write(self.sent)
        if progress is not None:
            progress(len(self.sent))
        if self.raised is not None:
            raise self.raised
        return self.answer


def streamed(session, folder=BACKUP_DIR, prefix="web-1"):
    sink = io.BytesIO()
    seen = []
    found = RemoteHost(session).stream_dbs_backup(
        PROFILE,
        passphrase=BACKUP_PASSPHRASE,
        prefix=prefix,
        folder=folder,
        sink=sink,
        progress=seen.append,
    )
    return found, sink.getvalue(), seen


def test_a_backup_is_streamed_with_its_passphrase_on_stdin(settings):
    settings.BACKUP_EXEC_TIMEOUT = 1234
    name = backup_filename("web-1")
    session = StreamingSession(
        result=RemoteResult(0, "", f"Streamed it.\n{summary_line(name)}\n")
    )

    found, received, seen = streamed(session)

    assert (found.name, found.size, found.sha256) == (name, len(CONTENT), DIGEST)
    assert found.path == f"{BACKUP_DIR}/{name}"
    assert received == CONTENT
    assert seen == [len(CONTENT)]
    [sent] = session.streams
    assert sent["stdin"] == BACKUP_PASSPHRASE
    assert sent["timeout"] == 1234
    argv, setup = argv_and_setup(sent["command"])
    assert argv == [
        PYTHON,
        "manage.py",
        "dbs_backup",
        "--stream",
        "--prefix",
        "web-1",
        "--passphrase-stdin",
        "--output-dir",
        BACKUP_DIR,
    ]
    assert setup == [
        f"cd {PROJECT_DIR} || exit 1",
        f"export DJANGO_SETTINGS_MODULE={SETTINGS_MODULE}",
    ]
    assert BACKUP_PASSPHRASE not in sent["command"]


def test_without_a_folder_the_server_keeps_its_copy_in_dbs_backup_dir():
    name = backup_filename("web-1")
    session = StreamingSession(result=RemoteResult(0, "", summary_line(name)))

    found, _, _ = streamed(session, folder="")

    assert "--output-dir" not in session.streams[0]["command"]
    assert found.path == ""


def test_a_stream_the_server_could_not_send_whole_is_kept_on_the_server():
    name = backup_filename("web-1")
    session = StreamingSession(
        result=RemoteResult(0, "", summary_line(name, kept_on_server=True))
    )

    with pytest.raises(StreamBroken):
        streamed(session)


def test_a_connection_lost_mid_stream_is_a_broken_stream():
    session = StreamingSession(
        failure=StreamInterrupted(f"The connection was lost: {BACKUP_PASSPHRASE}")
    )

    with pytest.raises(StreamBroken) as broken:
        streamed(session)

    assert BACKUP_PASSPHRASE not in broken.value.output


def test_a_failed_stream_keeps_the_end_of_stderr_and_never_the_passphrase():
    printed = "x" * 2000 + f" read {BACKUP_PASSPHRASE}\nCommandError: no database"
    session = StreamingSession(result=RemoteResult(1, "", printed))

    with pytest.raises(RemoteCommandFailed) as failed:
        streamed(session)

    assert type(failed.value) is RemoteCommandFailed
    assert len(failed.value.output) == 500
    assert failed.value.output.endswith("CommandError: no database")
    assert BACKUP_PASSPHRASE not in failed.value.output


def test_a_server_whose_django_dbs_cannot_stream_is_too_old():
    session = StreamingSession(
        result=RemoteResult(2, "", "manage.py dbs_backup: error: unrecognized arguments: --stream")
    )

    with pytest.raises(DbsTooOld) as raised:
        streamed(session)

    assert raised.value.needs == "0.7.0"
    assert "Upgrade it to 0.7.0 or later." in str(raised.value.detail)


@pytest.mark.parametrize(
    "stderr",
    [
        "",
        "Streamed it.",
        "[1, 2]",
        json.dumps({"name": backup_filename("other"), "size": 1, "sha256": DIGEST}),
        json.dumps({"name": "../web-1-20261013-000000Z.dbs", "size": 1, "sha256": DIGEST}),
        json.dumps({"name": backup_filename("web-1"), "size": "1", "sha256": DIGEST}),
        json.dumps({"name": backup_filename("web-1"), "size": True, "sha256": DIGEST}),
        json.dumps({"name": backup_filename("web-1"), "size": 1, "sha256": "abc"}),
    ],
)
def test_a_summary_line_that_does_not_describe_one_backup_fails_the_stream(stderr):
    session = StreamingSession(result=RemoteResult(0, "", stderr))

    with pytest.raises(RemoteCommandFailed) as failed:
        streamed(session)

    assert type(failed.value) is RemoteCommandFailed


def argv_and_setup(script: str):
    body = shlex.split(script)[2]
    lines = body.splitlines()
    return shlex.split(lines[-1][len("exec ") :]), lines[:-1]


def server_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "backups"
    folder.mkdir()
    return folder


def test_the_backups_waiting_on_the_server_are_its_prefix_names_oldest_first(tmp_path):
    folder = server_folder(tmp_path)
    newer = "web-1-20261013-120000Z.dbs"
    older = "web-1-20261012-120000Z.dbs"
    for name in (newer, older, "web-1-plan-20261013-120000Z.dbs", "web-1.dbs", "notes.txt"):
        (folder / name).write_bytes(b"x" * 3)
    (folder / "web-1-20261013-130000Z.dbs").mkdir()

    found = RemoteHost(FakeSession(sftp=LocalSftp())).waiting_backups(
        PROFILE, str(folder), "web-1"
    )

    assert [(item.name, item.size) for item in found] == [(older, 3), (newer, 3)]
    assert found[0].path == f"{folder}/{older}"
    assert found[0].mtime is not None


def test_a_backup_folder_that_is_not_there_has_nothing_waiting(tmp_path):
    remote = RemoteHost(FakeSession(sftp=LocalSftp()))

    assert remote.waiting_backups(PROFILE, str(tmp_path / "missing"), "web-1") == []
    assert remote.waiting_backups(PROFILE, "", "web-1") == []
    assert remote.backup_folder(PROFILE, str(tmp_path)) == str(tmp_path)


def test_a_waiting_backup_is_pulled_whole_and_its_digest_read(tmp_path):
    folder = server_folder(tmp_path)
    path = folder / backup_filename("web-1")
    path.write_bytes(CONTENT)
    remote = RemoteHost(LocalSession())
    sink = io.BytesIO()
    seen = []

    remote.pull_backup(PROFILE, str(path), sink, seen.append)

    assert sink.getvalue() == CONTENT
    assert seen[-1] == len(CONTENT)
    assert remote.backup_sha256(PROFILE, str(path)) == DIGEST


def test_a_backup_gone_before_it_is_pulled_is_not_found(tmp_path):
    remote = RemoteHost(FakeSession(sftp=LocalSftp()))

    with pytest.raises(RemoteNotFound):
        remote.pull_backup(PROFILE, str(tmp_path / "gone.dbs"), io.BytesIO())


def test_a_server_copy_is_removed_and_one_already_gone_is_fine(tmp_path):
    folder = server_folder(tmp_path)
    path = folder / backup_filename("web-1")
    path.write_bytes(CONTENT)
    remote = RemoteHost(FakeSession(sftp=LocalSftp()))

    remote.remove_backup(PROFILE, str(path))
    remote.remove_backup(PROFILE, str(path))

    assert list(folder.iterdir()) == []


def test_only_partials_left_for_an_hour_are_swept_from_the_backup_folder(tmp_path):
    folder = server_folder(tmp_path)
    stale = folder / partial_name(backup_filename("web-1"))
    legacy = folder / f"{backup_filename('web-1', ordinal=2)}.part"
    fresh = folder / partial_name(backup_filename("web-1", ordinal=3))
    unrelated = folder / "notes.part"
    for path in (stale, legacy, fresh, unrelated):
        path.write_bytes(b"x")
    for path in (stale, legacy, unrelated):
        os.utime(path, (1_000_000_000, 1_000_000_000))

    removed = RemoteHost(FakeSession(sftp=LocalSftp())).sweep_partials(str(folder))

    assert removed == [stale.name]
    assert sorted(path.name for path in folder.iterdir()) == sorted(
        [legacy.name, fresh.name, unrelated.name]
    )


def test_sweeping_a_folder_that_cannot_be_listed_removes_nothing(tmp_path):
    remote = RemoteHost(FakeSession(sftp=LocalSftp()))

    assert remote.sweep_partials(str(tmp_path / "missing")) == []


class LocalSession(FakeSession):
    def __init__(self) -> None:
        super().__init__(sftp=LocalSftp())

    def run(self, command, *, stdin_line=None, timeout=None):
        self.commands.append((command, stdin_line, timeout))
        done = run_locally(command)
        return RemoteResult(done.returncode, done.stdout, done.stderr)


class AnsweringSession(FakeSession):
    def __init__(self, *answers: RemoteResult | Exception) -> None:
        super().__init__(sftp=LocalSftp())
        self.answers = list(answers)

    def run(self, command, *, stdin_line=None, timeout=None):
        self.commands.append((command, stdin_line, timeout))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def server_tree(root: Path) -> dict[str, bytes]:
    files = {
        "srv/app/media/a.txt": b"alpha",
        "srv/app/media/it's $(here).txt": b"quoted",
        "srv/app/-n": b"dash",
        "etc/app.conf": b"setting=1",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return files


def members(archive: Path) -> dict[str, bytes]:
    with tarfile.open(archive, "r:gz") as tar:
        return {
            member.name: tar.extractfile(member).read()
            for member in tar.getmembers()
            if member.isfile()
        }


def test_an_archive_packs_each_path_relative_to_the_root_and_reports_its_digest(
    tmp_path,
):
    root = tmp_path / "server"
    files = server_tree(root)
    hostile = root / "$(echo pwned); `id` && x"
    hostile.mkdir()
    (hostile / "x").write_bytes(b"x")
    remote_dir = tmp_path / "var" / "backups" / "dbs"
    session = LocalSession()

    archive = RemoteHost(session).archive(
        [str(root / "srv" / "app"), str(root / "etc" / "app.conf"), str(hostile)],
        str(remote_dir),
        "web-1-files-20261001-120000Z.tar.gz",
        timeout=99,
    )

    path = remote_dir / "web-1-files-20261001-120000Z.tar.gz"
    assert archive.remote_path == str(path)
    assert archive.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert archive.warning == ""
    prefix = str(root).lstrip("/")
    assert members(path) == {
        **{f"{prefix}/{name}": content for name, content in files.items()},
        f"{prefix}/$(echo pwned); `id` && x/x": b"x",
    }
    assert stat.S_IMODE(remote_dir.stat().st_mode) == 0o700
    assert [timeout for _, _, timeout in session.commands] == [99, 99]


def test_an_archive_is_made_from_argv_alone():
    session = AnsweringSession(
        RemoteResult(0, "", ""), RemoteResult(0, f"{'a' * 64}  /b/x.tar.gz\n", "")
    )
    session.sftp.stat = lambda path: None

    RemoteHost(session).archive(["/srv/app", "/-rf", "/"], "/b", "x.tar.gz", timeout=5)

    assert [command for command, _, _ in session.commands] == [
        build_script(
            ["tar", "-czf", "/b/x.tar.gz", "-C", "/", "--", "srv/app", "-rf", "."]
        ),
        build_script(["sha256sum", "--", "/b/x.tar.gz"]),
    ]


def test_a_file_that_changed_while_tar_read_it_is_a_warning(tmp_path):
    session = AnsweringSession(
        RemoteResult(1, "", "tar: srv/app/db.log: file changed as we read it\n"),
        RemoteResult(0, f"{'b' * 64}  {tmp_path}/x.tar.gz\n", ""),
    )

    archive = RemoteHost(session).archive(
        ["/srv/app"], str(tmp_path), "x.tar.gz", timeout=5
    )

    assert (archive.sha256, archive.warning) == ("b" * 64, "files_changed")


def test_a_digest_of_an_escaped_path_is_still_read(tmp_path):
    session = AnsweringSession(
        RemoteResult(0, "", ""),
        RemoteResult(0, f"\\{'c' * 64}  {tmp_path}/x\\\\y.tar.gz\n", ""),
    )

    archive = RemoteHost(session).archive(
        ["/srv"], str(tmp_path), "x.tar.gz", timeout=5
    )

    assert archive.sha256 == "c" * 64


def test_an_archive_tar_cannot_make_fails_with_its_output_and_leaves_nothing(tmp_path):
    root = tmp_path / "server"
    server_tree(root)
    remote_dir = tmp_path / "backups"

    with pytest.raises(ArchiveFailed) as failed:
        RemoteHost(LocalSession()).archive(
            [str(root / "srv"), str(root / "missing")],
            str(remote_dir),
            "x.tar.gz",
            timeout=30,
        )

    assert failed.value.status_code == 502
    assert failed.value.default_code == "archive_failed"
    assert "missing" in failed.value.output
    assert len(failed.value.output) <= 500
    assert list(remote_dir.iterdir()) == []


@pytest.mark.parametrize("status", [2, 127, -1])
def test_any_other_tar_status_is_a_failed_archive(tmp_path, status):
    session = AnsweringSession(RemoteResult(status, "", "x" * 2000 + "tar: fatal"))

    with pytest.raises(ArchiveFailed) as failed:
        RemoteHost(session).archive(["/srv"], str(tmp_path), "x.tar.gz", timeout=5)

    assert failed.value.output.endswith("tar: fatal")
    assert len(failed.value.output) == 500
    assert len(session.commands) == 1


@pytest.mark.parametrize(
    "digest",
    [
        RemoteResult(1, "", "sha256sum: x: Permission denied"),
        RemoteResult(0, "garbage\n", ""),
    ],
)
def test_a_digest_that_cannot_be_read_is_remote_command_failed(tmp_path, digest):
    session = AnsweringSession(RemoteResult(0, "", ""), digest)

    with pytest.raises(RemoteCommandFailed) as failed:
        RemoteHost(session).archive(["/srv"], str(tmp_path), "x.tar.gz", timeout=5)

    assert type(failed.value) is RemoteCommandFailed


@pytest.mark.parametrize("failure", TRANSPORT_FAILURES)
def test_a_transport_failure_while_archiving_is_remote_command_failed(
    tmp_path, failure
):
    with pytest.raises(RemoteCommandFailed) as failed:
        RemoteHost(AnsweringSession(failure)).archive(
            ["/srv"], str(tmp_path), "x.tar.gz", timeout=5
        )

    assert type(failed.value) is RemoteCommandFailed


def test_a_directory_that_cannot_be_made_is_remote_command_failed(tmp_path):
    session = AnsweringSession()

    def refuse(path, mode=0o777):
        raise PermissionError(13, "Permission denied")

    session.sftp.mkdir = refuse

    with pytest.raises(RemoteCommandFailed) as failed:
        RemoteHost(session).archive(
            ["/srv"], str(tmp_path / "backups"), "x.tar.gz", timeout=5
        )

    assert failed.value.output == f"{tmp_path}/backups: [Errno 13] Permission denied"
    assert session.commands == []


@pytest.mark.parametrize("name", ["", ".", "..", "a/b.tar.gz", "/x.tar.gz"])
def test_an_archive_is_named_with_one_file_name(tmp_path, name):
    with pytest.raises(ValueError, match="Not a file name"):
        RemoteHost(AnsweringSession()).archive(["/srv"], str(tmp_path), name, timeout=5)


def test_an_archive_of_nothing_is_refused(tmp_path):
    with pytest.raises(ValueError, match="Nothing to archive"):
        RemoteHost(AnsweringSession()).archive([], str(tmp_path), "x.tar.gz", timeout=5)


def test_a_remote_file_is_read_ahead_and_closed_after(tmp_path):
    path = tmp_path / "x.tar.gz"
    path.write_bytes(b"archive bytes")
    session = LocalSession()

    with RemoteHost(session).open_file(str(path)) as remote:
        assert remote.read(7) == b"archive"
        assert remote.read() == b" bytes"

    [handle] = session.sftp.opened
    assert handle.prefetched
    assert handle.closed


def test_a_remote_file_is_closed_when_the_block_fails(tmp_path):
    path = tmp_path / "x.tar.gz"
    path.write_bytes(b"archive bytes")
    session = LocalSession()

    with pytest.raises(ZeroDivisionError), RemoteHost(session).open_file(str(path)):
        1 / 0

    assert session.sftp.opened[0].closed


def test_a_remote_file_that_is_not_there_is_remote_command_failed(tmp_path):
    remote = RemoteHost(LocalSession())

    with (
        pytest.raises(RemoteCommandFailed) as failed,
        remote.open_file(str(tmp_path / "gone")),
    ):
        pass

    assert failed.value.output.startswith(f"{tmp_path}/gone: ")


@pytest.mark.parametrize("failure", TRANSPORT_FAILURES)
def test_a_read_ahead_the_connection_fails_is_remote_command_failed_and_closes(
    tmp_path, failure
):
    path = tmp_path / "x.tar.gz"
    path.write_bytes(b"archive bytes")
    session = LocalSession()
    opened = session.sftp.open

    def failing_prefetch(path, mode="r"):
        handle = opened(path, mode)
        handle.prefetch = lambda: (_ for _ in ()).throw(failure)
        return handle

    session.sftp.open = failing_prefetch

    with pytest.raises(RemoteCommandFailed), RemoteHost(session).open_file(str(path)):
        pass

    assert session.sftp.opened[0].closed


@pytest.mark.parametrize("failure", TRANSPORT_FAILURES)
def test_a_read_the_connection_fails_is_remote_command_failed(tmp_path, failure):
    path = tmp_path / "x.tar.gz"
    path.write_bytes(b"archive bytes")
    session = LocalSession()

    with RemoteHost(session).open_file(str(path)) as remote:
        session.sftp.opened[0].read = lambda size=-1: (_ for _ in ()).throw(failure)
        with pytest.raises(RemoteCommandFailed):
            remote.read(4)


def test_a_removed_file_is_gone_and_one_already_gone_is_fine(tmp_path):
    path = tmp_path / "x.tar.gz"
    path.write_bytes(b"x")
    remote = RemoteHost(LocalSession())

    remote.remove(str(path))
    remote.remove(str(path))

    assert not path.exists()


def test_a_file_the_server_refuses_to_remove_is_remote_command_failed(tmp_path):
    session = LocalSession()

    def refuse(path):
        raise PermissionError(13, "Permission denied")

    session.sftp.remove = refuse

    with pytest.raises(RemoteCommandFailed) as failed:
        RemoteHost(session).remove(str(tmp_path / "x.tar.gz"))

    assert "Permission denied" in failed.value.output


ARCHIVES = re.compile(r"web-1-files-\d{8}-\d{6}Z(?:-\d+)?\.tar\.gz")


def dated(directory: Path, name: str, moment: int) -> Path:
    path = directory / name
    path.write_bytes(name.encode())
    os.utime(path, (moment, moment))
    return path


@pytest.mark.parametrize(
    ("keep", "left"),
    [
        (0, []),
        (1, ["newest"]),
        (2, ["middle", "newest"]),
        (5, ["oldest", "middle", "newest"]),
    ],
)
def test_pruning_keeps_the_newest_matching_files_and_nothing_else_is_touched(
    tmp_path, keep, left
):
    named = {
        "oldest": dated(tmp_path, "web-1-files-20261001-120000Z.tar.gz", 1_000),
        "middle": dated(tmp_path, "web-1-files-20261002-120000Z.tar.gz", 2_000),
        "newest": dated(tmp_path, "web-1-files-20261002-120000Z-2.tar.gz", 3_000),
    }
    others = [
        dated(tmp_path, "web-1-files-20261001-120000Z.dbs", 0),
        dated(tmp_path, "web-1-files-other-20261001-120000Z.tar.gz", 0),
        dated(tmp_path, "notes.txt", 0),
    ]
    (tmp_path / "web-1-files-20261003-120000Z.tar.gz").mkdir()

    RemoteHost(LocalSession()).prune(str(tmp_path), ARCHIVES, keep)

    assert sorted(name for name, path in named.items() if path.exists()) == sorted(left)
    assert all(path.exists() for path in others)
    assert (tmp_path / "web-1-files-20261003-120000Z.tar.gz").is_dir()


def test_pruning_a_directory_that_is_not_there_removes_nothing(tmp_path):
    RemoteHost(LocalSession()).prune(str(tmp_path / "missing"), ARCHIVES, 0)


@pytest.mark.parametrize("failure", TRANSPORT_FAILURES)
def test_a_listing_the_connection_fails_is_remote_command_failed(tmp_path, failure):
    session = LocalSession()

    def fail(path):
        raise failure

    session.sftp.listdir_attr = fail

    with pytest.raises(RemoteCommandFailed):
        RemoteHost(session).prune(str(tmp_path), ARCHIVES, 1)


def test_a_folder_lists_its_regular_files_by_name_with_size_and_time(tmp_path):
    dated(tmp_path, "b.sql.gz", 1_790_086_400)
    dated(tmp_path, "a.sql.gz", 1_790_000_000)
    (tmp_path / "it's $(here).txt").write_bytes(b"quoted")
    os.utime(tmp_path / "it's $(here).txt", (1_000, 1_000))
    (tmp_path / "folder.sql.gz").mkdir()
    (tmp_path / "link.sql.gz").symlink_to(tmp_path / "a.sql.gz")
    (tmp_path / "dangling.sql.gz").symlink_to(tmp_path / "gone")

    listed = RemoteHost(LocalSession()).list_files(str(tmp_path))

    assert listed == [
        RemoteFile(
            name="a.sql.gz",
            path=f"{tmp_path}/a.sql.gz",
            size=len(b"a.sql.gz"),
            mtime=datetime.fromtimestamp(1_790_000_000, dt_timezone.utc),
        ),
        RemoteFile(
            name="b.sql.gz",
            path=f"{tmp_path}/b.sql.gz",
            size=len(b"b.sql.gz"),
            mtime=datetime.fromtimestamp(1_790_086_400, dt_timezone.utc),
        ),
        RemoteFile(
            name="it's $(here).txt",
            path=f"{tmp_path}/it's $(here).txt",
            size=len(b"quoted"),
            mtime=datetime.fromtimestamp(1_000, dt_timezone.utc),
        ),
    ]


def test_an_entry_the_server_sends_no_type_for_is_not_listed(tmp_path):
    session = LocalSession()
    session.sftp.listdir_attr = lambda path: [SFTPAttributes()]

    assert RemoteHost(session).list_files(str(tmp_path)) == []


def test_a_file_the_server_gives_no_size_or_time_is_listed_without_them(tmp_path):
    session = LocalSession()
    entry = SFTPAttributes()
    entry.filename, entry.st_mode = "a.sql.gz", stat.S_IFREG | 0o600
    session.sftp.listdir_attr = lambda path: [entry]

    assert RemoteHost(session).list_files("/var/backups") == [
        RemoteFile(name="a.sql.gz", path="/var/backups/a.sql.gz", size=None, mtime=None)
    ]


def test_listing_a_folder_that_is_not_there_is_remote_not_found(tmp_path):
    with pytest.raises(RemoteNotFound) as missing:
        RemoteHost(LocalSession()).list_files(str(tmp_path / "gone"))

    assert (missing.value.status_code, missing.value.default_code) == (
        404,
        "remote_not_found",
    )


@pytest.mark.parametrize("code", [errno.EACCES, errno.EPERM])
def test_listing_a_folder_the_user_may_not_read_is_remote_permission_denied(
    tmp_path, code
):
    session = LocalSession()

    def refuse(path):
        raise OSError(code, "Permission denied")

    session.sftp.listdir_attr = refuse

    with pytest.raises(RemotePermissionDenied) as refused:
        RemoteHost(session).list_files(str(tmp_path))

    assert (refused.value.status_code, refused.value.default_code) == (
        403,
        "remote_permission_denied",
    )


@pytest.mark.parametrize(
    "failure",
    [
        *TRANSPORT_FAILURES,
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
    ],
)
def test_a_listing_that_fails_otherwise_is_remote_command_failed(tmp_path, failure):
    session = LocalSession()

    def fail(path):
        raise failure

    session.sftp.listdir_attr = fail

    with pytest.raises(RemoteCommandFailed) as failed:
        RemoteHost(session).list_files(str(tmp_path))

    assert type(failed.value) is RemoteCommandFailed
    assert failed.value.output.startswith(f"{tmp_path}:")
