from __future__ import annotations

import io
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from dbs.exceptions import DBSError
from dbs.manager.servers.exceptions import (
    FileTooLarge,
    RemoteCommandFailed,
    RemoteCommandTimedOut,
    RemoteNotFound,
    RestoreFailed,
)
from dbs.manager.servers.gateways import ContainerTarget, DbsProfile, RemoteHost
from dbs.manager.servers.gateways.ssh_gateway import (
    MODE_OF,
    READ_SMALL,
    RECEIVE_FILE,
    SWEEP_STALE,
)
from dbs.transports import RemoteResult
from tests.manager.remote import argv_of
from tests.manager.servers.support import BACKUP_PASSPHRASE, LocalSftpSession

CONTAINER = "shop-web-1"
CONTAINER_TMP = "dbs.manager.servers.gateways.ssh_gateway.CONTAINER_TMP"
BACKUP = b"DBS\x00 a django-dbs container, as far as this test is concerned"
INTERACTIVE_FLAGS = ("-i",)
VALUED_FLAGS = ("-u", "-w", "-e")
MANAGE = """
import json, os, shutil, stat, sys
record = {record!r}
arguments = sys.argv[1:]
path = arguments[1]
shutil.copyfile(path, os.path.join(record, "sent"))
with open(os.path.join(record, "seen.json"), "w") as handle:
    json.dump(
        {{
            "argv": arguments,
            "stdin": sys.stdin.readline().rstrip("\\n"),
            "mode": oct(stat.S_IMODE(os.stat(path).st_mode)),
            "cwd": os.getcwd(),
        }},
        handle,
    )
print("Flush would first delete 17 existing rows.")
print("Dry run: 42 records and 3 files would be restored; nothing was written.")
"""


class LocalContainer(LocalSftpSession):
    def __init__(self, *, refused: tuple[str, ...] = (), failure=None) -> None:
        super().__init__()
        self.refused = refused
        self.failure = failure
        self.runs: list[dict] = []

    def run(self, script, *, stdin_line=None, timeout=None):
        argv, setup = argv_of(script)
        self.runs.append({"argv": argv, "setup": setup, "stdin": stdin_line})
        if self.failure is not None:
            raise self.failure
        return self.inside(argv, None if stdin_line is None else f"{stdin_line}\n")

    def feed(self, script, source, *, stdin_line=None, timeout=None):
        argv, setup = argv_of(script)
        data = source.read()
        self.runs.append({"argv": argv, "setup": setup, "fed": data})
        if self.failure is not None:
            raise self.failure
        return self.inside(argv, data)

    def inside(self, argv, data):
        if argv[:2] == ["timeout", "-k"]:
            argv = argv[4:]
        assert argv[:2] == ["docker", "exec"], argv
        rest, options = argv[2:], {"env": {}, "cwd": None}
        while rest[0] in (*INTERACTIVE_FLAGS, *VALUED_FLAGS):
            flag = rest.pop(0)
            if flag == "-w":
                options["cwd"] = rest.pop(0)
            elif flag == "-e":
                name, _, value = rest.pop(0).partition("=")
                options["env"][name] = value
            elif flag == "-u":
                rest.pop(0)
        assert rest[0] == CONTAINER
        command = rest[1:]
        if command[:2] == ["timeout", "-k"]:
            command = command[4:]
        if command[0] in self.refused:
            return RemoteResult(1, "", f"{command[0]}: Operation not permitted")
        if command[0] == "python":
            command = [sys.executable, *command[1:]]
        try:
            done = subprocess.run(
                command,
                input=data.encode() if isinstance(data, str) else data,
                capture_output=True,
                cwd=options["cwd"],
                env={**os.environ, **options["env"]},
                check=False,
                timeout=30,
            )
        except FileNotFoundError:
            return RemoteResult(127, "", f"exec: {command[0]}: not found")
        return RemoteResult(
            done.returncode,
            done.stdout.decode(errors="replace"),
            done.stderr.decode(errors="replace"),
        )


def profile(**fields) -> DbsProfile:
    return DbsProfile(
        python=fields.pop("python", "python"),
        manage=fields.pop("manage", "manage.py"),
        settings_module=fields.pop("settings_module", "shop.settings"),
        container=ContainerTarget(container=CONTAINER, **fields),
    )


@pytest.fixture(autouse=True)
def umask():
    previous = os.umask(0o022)
    yield
    os.umask(previous)


def test_a_small_file_is_read_inside_the_container_without_the_settings(tmp_path):
    secret = tmp_path / ".env"
    secret.write_bytes(b"SECRET_KEY=x\n")
    session = LocalContainer()

    data = RemoteHost(session).read_in_container(profile(), str(secret), 65536)

    assert data == b"SECRET_KEY=x\n"
    [run] = session.runs
    assert run["argv"] == [
        "docker",
        "exec",
        CONTAINER,
        "python",
        "-c",
        READ_SMALL,
        str(secret),
        "65536",
    ]


def test_a_file_over_the_limit_in_the_container_is_too_large(tmp_path):
    secret = tmp_path / ".env"
    secret.write_bytes(b"A" * 65)

    with pytest.raises(FileTooLarge):
        RemoteHost(LocalContainer()).read_in_container(profile(), str(secret), 64)


@pytest.mark.parametrize("kind", ["missing", "folder"])
def test_what_is_not_a_file_in_the_container_is_not_found(tmp_path, kind):
    path = tmp_path / "thing"
    if kind == "folder":
        path.mkdir()

    with pytest.raises(RemoteNotFound):
        RemoteHost(LocalContainer()).read_in_container(profile(), str(path), 64)


def test_a_container_without_that_python_cannot_read(tmp_path):
    with pytest.raises(RemoteCommandFailed) as failed:
        RemoteHost(LocalContainer()).read_in_container(
            profile(python=str(tmp_path / "no-python")), str(tmp_path / ".env"), 64
        )

    assert "not found" in failed.value.output


def test_output_that_is_not_base64_is_remote_command_failed(tmp_path):
    class Garbled(LocalContainer):
        def inside(self, argv, data):
            return RemoteResult(0, "not base64 at all!", "")

    with pytest.raises(RemoteCommandFailed):
        RemoteHost(Garbled()).read_in_container(profile(), str(tmp_path / ".env"), 64)


def test_a_file_in_the_container_is_replaced_whole_and_keeps_its_mode(tmp_path):
    secret = tmp_path / ".env"
    secret.write_bytes(b"OLD=1\n")
    secret.chmod(0o640)
    session = LocalContainer()

    RemoteHost(session).replace_in_container(profile(), str(secret), b"NEW=2\n")

    assert secret.read_bytes() == b"NEW=2\n"
    assert stat.S_IMODE(secret.stat().st_mode) == 0o640
    assert sorted(path.name for path in tmp_path.iterdir()) == [".env"]
    asked, written = session.runs
    assert asked["argv"] == [
        "docker",
        "exec",
        CONTAINER,
        "python",
        "-c",
        MODE_OF,
        str(secret),
    ]
    assert written["argv"][:6] == [
        "docker",
        "exec",
        "-i",
        CONTAINER,
        "python",
        "-c",
    ]
    assert written["argv"][6:9] == [RECEIVE_FILE, str(secret), "6"]
    assert written["argv"][9] == "0o640"
    partial = Path(written["argv"][10])
    assert partial.parent == tmp_path
    assert partial.name.startswith("..env.part-")
    assert written["fed"] == b"NEW=2\n"
    assert all(b"NEW=2" not in part.encode() for part in written["argv"])


def test_a_file_that_is_not_there_yet_is_created_private(tmp_path):
    secret = tmp_path / ".env"

    RemoteHost(LocalContainer()).replace_in_container(
        profile(), str(secret), b"NEW=2\n"
    )

    assert secret.read_bytes() == b"NEW=2\n"
    assert stat.S_IMODE(secret.stat().st_mode) == 0o600


@pytest.mark.parametrize("path", ["relative/.env", "/", "/srv/app/", "/srv/.."])
def test_only_an_absolute_file_path_is_replaced_in_the_container(path):
    session = LocalContainer()

    with pytest.raises(ValueError):
        RemoteHost(session).replace_in_container(profile(), path, b"A=1\n")

    assert session.runs == []


def test_a_replacement_the_container_refuses_says_why_and_leaves_the_file(tmp_path):
    secret = tmp_path / ".env"
    secret.write_bytes(b"OLD=1\n")
    session = LocalContainer()
    session.inside = refusing_receive(session.inside)

    with pytest.raises(RemoteCommandFailed) as failed:
        RemoteHost(session).replace_in_container(profile(), str(secret), b"NEW=2\n")

    assert "Read-only file system" in failed.value.output
    assert secret.read_bytes() == b"OLD=1\n"


def refusing_receive(inside):
    def refused(argv, data):
        if RECEIVE_FILE in argv:
            return RemoteResult(1, "", "OSError: [Errno 30] Read-only file system")
        return inside(argv, data)

    return refused


def test_stale_partials_in_the_container_are_swept_and_counted(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    for folder in (first, second):
        folder.mkdir()
        stale = folder / ".dbs-restore-0123456789abcdef.dbs"
        stale.write_bytes(b"x")
        os.utime(stale, (1, 1))
    session = LocalContainer()

    removed = RemoteHost(session).sweep_in_container(profile(), str(first), str(second))

    assert removed == 2
    assert session.runs[0]["argv"] == [
        "docker",
        "exec",
        CONTAINER,
        "python",
        "-c",
        SWEEP_STALE,
        str(first),
        str(second),
    ]


@pytest.mark.parametrize(
    "session",
    [LocalContainer(refused=("python",)), LocalContainer(failure=DBSError("gone"))],
)
def test_a_sweep_that_cannot_run_removes_nothing(tmp_path, session):
    assert RemoteHost(session).sweep_in_container(profile(), str(tmp_path)) == 0


def test_bytes_are_fed_to_a_command_on_its_standard_input(tmp_path):
    target = tmp_path / "received"
    session = LocalContainer()

    result = RemoteHost(session).feed(
        [
            "docker",
            "exec",
            "-i",
            CONTAINER,
            "python",
            "-c",
            RECEIVE_FILE,
            str(target),
            "5",
        ],
        io.BytesIO(b"hello"),
    )

    assert result.ok
    assert target.read_bytes() == b"hello"
    assert session.runs[0]["fed"] == b"hello"


def test_a_fed_command_on_a_server_with_timeout_is_stopped_at_its_deadline(tmp_path):
    session = LocalContainer()

    RemoteHost(session, timeout_on_host=True).feed(
        ["docker", "exec", "-i", CONTAINER, "true"], io.BytesIO(b""), timeout=60
    )

    assert session.runs[0]["argv"][:4] == ["timeout", "-k", "30", "60"]


@pytest.mark.parametrize("status", [124, 137])
def test_a_fed_command_stopped_at_its_deadline_says_it_ran_out_of_time(status):
    class Stopped(LocalContainer):
        def inside(self, argv, data):
            return RemoteResult(status, "", "")

    with pytest.raises(RemoteCommandTimedOut):
        RemoteHost(Stopped(), timeout_on_host=True).feed(["true"], io.BytesIO(b""))


def test_a_feed_the_transport_breaks_is_remote_command_failed():
    with pytest.raises(RemoteCommandFailed) as failed:
        RemoteHost(LocalContainer(failure=DBSError("broken pipe"))).feed(
            ["true"], io.BytesIO(b"x")
        )

    assert "broken pipe" in failed.value.output


def test_a_python_fed_inside_the_container_is_bounded_inside_it(tmp_path):
    session = LocalContainer()

    RemoteHost(session, timeout_on_host=True, timeout_in_container=True).feed_python(
        profile(), ["-c", "import sys; sys.stdin.read()"], io.BytesIO(b"x"), timeout=60
    )

    assert session.runs[0]["argv"][:8] == [
        "docker",
        "exec",
        "-i",
        CONTAINER,
        "timeout",
        "-k",
        "30",
        "60",
    ]


def test_container_commands_are_refused_for_an_application_on_the_host():
    host = DbsProfile(python="python3", manage="manage.py", project_dir="/srv/app")
    remote = RemoteHost(LocalContainer())

    with pytest.raises(ValueError):
        remote.feed_python(host, ["-c", "pass"], io.BytesIO(b""))
    with pytest.raises(ValueError):
        remote.run_in_container(host, ["id"])
    with pytest.raises(ValueError):
        remote.run_engine(host, ["docker", "ps"])
    with pytest.raises(ValueError):
        remote.run_compose(profile(), ["ps"])


@pytest.fixture
def application(tmp_path, monkeypatch):
    record = tmp_path / "record"
    record.mkdir()
    workdir = tmp_path / "app"
    workdir.mkdir()
    (workdir / "manage.py").write_text(MANAGE.format(record=str(record)))
    staging = tmp_path / "container-tmp"
    staging.mkdir()
    monkeypatch.setattr(CONTAINER_TMP, str(staging))
    return {
        "record": record,
        "workdir": workdir,
        "staging": staging,
        "host": tmp_path / "host" / "backups",
    }


def restored(session, application, **options):
    return RemoteHost(session).restore_dbs_backup(
        io.BytesIO(BACKUP),
        profile=profile(workdir=str(application["workdir"])),
        passphrase=BACKUP_PASSPHRASE,
        remote_dir=str(application["host"]),
        flush=options.get("flush", True),
        dry_run=options.get("dry_run", True),
    )


def test_a_restore_streams_the_file_into_the_container_and_runs_dbs_restore_there(
    application,
):
    session = LocalContainer()

    report = restored(session, application)

    seen = json.loads((application["record"] / "seen.json").read_text())
    sent_as = seen["argv"][1]
    assert seen["argv"] == [
        "dbs_restore",
        sent_as,
        "--passphrase-stdin",
        "--flush",
        "--dry-run",
    ]
    assert Path(sent_as).parent == application["staging"]
    assert Path(sent_as).name.startswith(".dbs-restore-")
    assert (application["record"] / "sent").read_bytes() == BACKUP
    assert seen["mode"] == "0o600"
    assert seen["stdin"] == BACKUP_PASSPHRASE
    assert seen["cwd"] == str(application["workdir"])
    assert (report.records, report.files, report.flushed) == (42, 3, 17)
    assert report.copy_left == ""
    assert list(application["staging"].iterdir()) == []


def test_a_container_restore_leaves_nothing_on_the_host_and_runs_as_the_containers_user(
    application,
):
    session = LocalContainer()

    restored(session, application)

    received, ran, removed = session.runs
    assert received["argv"][:7] == [
        "docker",
        "exec",
        "-i",
        "-w",
        str(application["workdir"]),
        CONTAINER,
        "python",
    ]
    assert received["argv"][7:9] == ["-c", RECEIVE_FILE]
    assert received["argv"][10] == str(len(BACKUP))
    assert received["fed"] == BACKUP
    assert ran["argv"][-6:-4] == ["manage.py", "dbs_restore"]
    assert ran["stdin"] == BACKUP_PASSPHRASE
    assert removed["argv"][-4:] == ["rm", "-f", "--", received["argv"][9]]
    assert all("-u" not in run["argv"] for run in session.runs)
    assert all(BACKUP_PASSPHRASE not in " ".join(run["argv"]) for run in session.runs)
    assert session.sftp.opened == []
    assert not application["host"].exists()


def test_a_copy_the_container_will_not_remove_is_named_not_raised(application):
    session = LocalContainer(refused=("rm",))

    report = restored(session, application)

    [left] = list(application["staging"].iterdir())
    assert report.copy_left == str(left)
    assert report.records == 42


def test_a_file_the_container_could_not_take_stops_the_restore(application):
    session = LocalContainer()
    session.inside = refusing_receive(session.inside)

    with pytest.raises(RestoreFailed) as failed:
        restored(session, application)

    assert "Read-only file system" in failed.value.output
    assert not (application["record"] / "seen.json").exists()
    assert list(application["staging"].iterdir()) == []
