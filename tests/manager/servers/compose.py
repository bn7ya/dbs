from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

from dbs.manager.applications.services.application_service import IS_FILE, IS_FOLDER
from dbs.manager.servers.gateways import RemoteHost
from dbs.manager.servers.gateways.ssh_gateway import (
    LIST_FILES,
    MODE_OF,
    READ_SMALL,
    RECEIVE_FILE,
    SWEEP_STALE,
)
from dbs.manager.servers.services.pythons import VERSION_PROBE
from dbs.naming import backup_filename
from dbs.transports import RemoteResult
from dbs.transports.ssh import StreamInterrupted
from tests.manager.remote import argv_of
from tests.manager.servers.support import (
    REMOTE_DBS_VERSION,
    LocalSftpSession,
    dbs_backup,
)

CONNECT = "dbs.manager.servers.services.connection_service.connect"
HOST_UID = "1000"
COMPOSE_VERSION = "2.29.1"
ENGINE_VERSION = "27.3.1"
SYSTEM = "Linux 6.1.0-18-amd64"
CONTAINER_BACKUP_DIR = "/app/backups"
LOCAL_SCRIPTS = (READ_SMALL, MODE_OF, SWEEP_STALE, IS_FILE, IS_FOLDER)


class ComposeHost(LocalSftpSession):
    def __init__(
        self,
        container: Path,
        *,
        running: tuple[str, ...] = ("db", "backend"),
        with_dbs: tuple[str, ...] = ("backend",),
        container_uid: str = "10001",
        docker: bool = True,
        backup_fails: str = "",
        chown_fails: bool = False,
        backup_dir: str = CONTAINER_BACKUP_DIR,
        stream_breaks: bool = False,
        engine: str = "docker",
        dbs_version: str = REMOTE_DBS_VERSION,
    ) -> None:
        super().__init__()
        self.engine = engine
        self.dbs_version = dbs_version
        self.backup_dir = backup_dir
        self.stream_breaks = stream_breaks
        self.container = container
        self.running = running
        self.with_dbs = with_dbs
        self.container_uid = container_uid
        self.docker = docker
        self.backup_fails = backup_fails
        self.chown_fails = chown_fails
        self.owners: dict[str, str] = {}
        self.runs: list[dict] = []
        self.received: dict[str, bytes] = {}

    def inside(self, path: str) -> Path:
        return self.container / path.lstrip("/")

    def run(self, script, stdin_line=None, timeout=None):
        argv, setup = argv_of(script)
        self.runs.append({"argv": argv, "setup": setup, "stdin": stdin_line})
        if argv == ["uname", "-sr"]:
            return RemoteResult(0, f"{SYSTEM}\n", "")
        if argv[:1] != [self.engine]:
            return RemoteResult(127, "", f"{argv[0]}: not found")
        if not self.docker:
            return RemoteResult(127, "", f"sh: 1: {self.engine}: not found")
        if argv[1:2] == ["version"]:
            return RemoteResult(0, f"{ENGINE_VERSION}\n", "")
        if argv[1:2] == ["ps"]:
            wanted = next(
                part.rsplit("=", 1)[1]
                for part in argv
                if part.startswith("label=com.docker.compose.service=")
            )
            listed = f"shop-{wanted}-1\n" if wanted in self.running else ""
            return RemoteResult(0, listed, "")
        if argv[1:2] != ["compose"]:
            return RemoteResult(1, "", f"unknown {self.engine} command {argv[1]}")
        rest = compose_verb(argv)
        verb, arguments = rest[0], rest[1:]
        if verb == "version":
            return RemoteResult(0, f"{COMPOSE_VERSION}\n", "")
        if verb == "ps":
            return RemoteResult(0, "".join(f"{name}\n" for name in self.running), "")
        if verb == "cp":
            return self.copy(*arguments)
        if verb == "exec":
            return self.exec(arguments, stdin_line)
        return RemoteResult(1, "", f"unknown docker compose command {verb}")

    def copy(self, source: str, destination: str) -> RemoteResult:
        if ":" in source:
            service, path = source.split(":", 1)
            if service not in self.running:
                return RemoteResult(1, "", f'service "{service}" is not running')
            if not self.inside(path).exists():
                return RemoteResult(1, "", f"Could not find the file {path}")
            shutil.copy2(self.inside(path), destination)
            return RemoteResult(0, "", "")
        service, path = destination.split(":", 1)
        if service not in self.running:
            return RemoteResult(1, "", f'service "{service}" is not running')
        target = self.inside(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        self.owners[path] = HOST_UID
        return RemoteResult(0, "", "")

    def stream(
        self,
        script,
        sink,
        stdin_line=None,
        timeout=None,
        progress=None,
        idle_timeout=None,
        on_stderr_line=None,
    ):
        argv, setup = argv_of(script)
        self.runs.append(
            {"argv": argv, "setup": setup, "stdin": stdin_line, "streamed": True}
        )
        rest = compose_verb(argv)
        options, service, command = self.split_exec(rest[1:])
        if service not in self.running:
            return RemoteResult(1, "", f'service "{service}" is not running')
        if command[:2] == ["cat", "--"]:
            sink.write(self.inside(command[2]).read_bytes())
            return RemoteResult(0, "", "")
        if command[:2] == ["tail", "-c"] and command[3] == "--":
            start = int(command[2].lstrip("+")) - 1
            sink.write(self.inside(command[4]).read_bytes()[start:])
            return RemoteResult(0, "", "")
        if self.backup_fails:
            return RemoteResult(1, "", self.backup_fails)
        prefix = command[command.index("--prefix") + 1]
        folder = (
            command[command.index("--output-dir") + 1]
            if "--output-dir" in command
            else self.backup_dir
        )
        data = dbs_backup(stdin_line)
        directory = self.inside(folder)
        directory.mkdir(parents=True, exist_ok=True)
        name = next(
            backup_filename(prefix, ordinal=ordinal)
            for ordinal in range(1, 1000)
            if not (directory / backup_filename(prefix, ordinal=ordinal)).exists()
        )
        (directory / name).write_bytes(data)
        self.owners[f"{folder}/{name}"] = self.container_uid
        if self.stream_breaks:
            sink.write(data[: len(data) // 2])
            raise StreamInterrupted("The connection was lost: Socket is closed")
        sink.write(data)
        summary = {
            "name": name,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        return RemoteResult(0, "", f"Streamed {name}\n{json.dumps(summary)}\n")

    def feed(self, script, source, stdin_line=None, timeout=None):
        argv, setup = argv_of(script)
        self.runs.append(
            {"argv": argv, "setup": setup, "stdin": stdin_line, "fed": True}
        )
        if argv[:2] != [self.engine, "compose"]:
            return RemoteResult(127, "", f"{argv[0]}: not found")
        rest = compose_verb(argv)
        options, service, command = self.split_exec(rest[1:])
        if service not in self.running:
            return RemoteResult(1, "", f'service "{service}" is not running')
        if command[1:3] == ["-c", RECEIVE_FILE]:
            return self.receive(command[3:], source, options["user"])
        return self.exec(rest[1:], stdin_line)

    def receive(self, arguments: list[str], source, user: str) -> RemoteResult:
        path, size = arguments[0], int(arguments[1])
        mode = int(arguments[2], 8) if len(arguments) > 2 else 0o600
        partial = arguments[3] if len(arguments) > 3 else ""
        target = self.inside(partial or path)
        if target.exists():
            return RemoteResult(1, "", f"FileExistsError: {partial or path}")
        data = source.read(size)
        if len(data) < size:
            return RemoteResult(5, "", "")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(mode)
        if partial:
            os.replace(target, self.inside(path))
        self.owners[path] = user
        self.received[path] = data
        return RemoteResult(0, "", "")

    def listed(self, folder: str) -> list:
        return _listed_entries(self.inside(folder))

    def split_exec(self, arguments: list[str]) -> tuple[dict, str, list[str]]:
        options = {"user": self.container_uid, "env": {}, "workdir": ""}
        while arguments[0] in ("-T", "-i", "-u", "-w", "-e"):
            flag = arguments.pop(0)
            if flag == "-u":
                options["user"] = arguments.pop(0)
            elif flag == "-w":
                options["workdir"] = arguments.pop(0)
            elif flag == "-e":
                name, _, value = arguments.pop(0).partition("=")
                options["env"][name] = value
        return options, arguments[0], arguments[1:]

    def exec(self, arguments: list[str], stdin_line: str | None) -> RemoteResult:
        options, service, command = self.split_exec(arguments)
        if service not in self.running:
            return RemoteResult(1, "", f'service "{service}" is not running')
        if command[:2] == ["sha256sum", "--"]:
            digest = hashlib.sha256(self.inside(command[2]).read_bytes()).hexdigest()
            return RemoteResult(0, f"{digest}  {command[2]}\n", "")
        if command[1:3] == ["-c", LIST_FILES]:
            return RemoteResult(0, json.dumps(self.listed(command[3])), "")
        if command == ["id", "-u"]:
            return RemoteResult(0, f"{self.container_uid}\n", "")
        if command[:1] == ["chown"]:
            if self.chown_fails or options["user"] != "0":
                return RemoteResult(1, "", "chown: Operation not permitted")
            self.owners[command[2]] = command[1]
            return RemoteResult(0, "", "")
        if command[:2] == ["rm", "-f"]:
            path = command[3] if command[2:3] == ["--"] else command[2]
            owner = self.owners.get(path, self.container_uid)
            if options["user"] not in ("0", owner):
                return RemoteResult(1, "", "rm: Permission denied")
            self.inside(path).unlink(missing_ok=True)
            self.owners.pop(path, None)
            return RemoteResult(0, "", "")
        if command[1:2] == ["-c"] and command[2:3] and command[2] in LOCAL_SCRIPTS:
            return self.script(command[2], command[3:])
        if command[1:] == ["-c", VERSION_PROBE]:
            if service in self.with_dbs and command[0] in ("python", "python3"):
                return RemoteResult(0, f"{self.dbs_version}\n", "")
            return RemoteResult(127, "", f"exec: {command[0]}: not found")
        if service not in self.with_dbs:
            return RemoteResult(127, "", f"exec: {command[0]}: not found")
        return self.manage(command[2:], stdin_line, options)

    def script(self, source: str, arguments: list[str]) -> RemoteResult:
        mapped = [
            str(self.inside(argument)) if argument.startswith("/") else argument
            for argument in arguments
        ]
        done = subprocess.run(
            [sys.executable, "-c", source, *mapped],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        return RemoteResult(done.returncode, done.stdout, done.stderr)

    def manage(
        self, command: list[str], stdin_line: str | None, options: dict
    ) -> RemoteResult:
        if command[:2] == ["dbs_backup", "--help"]:
            return RemoteResult(0, "usage: manage.py dbs_backup", "")
        if command[:1] == ["dbs_backup"]:
            if self.backup_fails:
                return RemoteResult(1, "", self.backup_fails)
            target = self.inside(command[1])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(dbs_backup(stdin_line))
            target.chmod(0o600)
            self.owners[command[1]] = self.container_uid
            return RemoteResult(0, f"Wrote {command[1]}", "")
        if command[:1] == ["dbs_restore"]:
            path = command[1]
            if self.owners.get(path) != self.container_uid:
                return RemoteResult(
                    1, "", f"CommandError: Cannot read {path}: Permission denied"
                )
            verb = "would be restored" if "--dry-run" in command else "Restored"
            if verb == "Restored":
                return RemoteResult(0, "Restored 3 records and 0 files.", "")
            return RemoteResult(
                0, "Dry run: 3 records and 0 files would be restored", ""
            )
        if command[:2] == ["dbs_connection", "--json"]:
            return RemoteResult(0, json.dumps({"remote_backup_dir": self.backup_dir}), "")
        if command[:2] == ["dbs_key", "--show"]:
            return RemoteResult(0, "derived-passphrase-from-the-container\n", "")
        if command[:3] == ["dbs", "health", "--json"]:
            return RemoteResult(0, '{"status": "ok", "checks": []}', "")
        if command[:2] == ["migrate", "--check"]:
            return RemoteResult(0, "", "")
        if command[:1] == ["migrate"]:
            return RemoteResult(0, "No migrations to apply.", "")
        return RemoteResult(1, "", f"Unknown command: {command}")


def compose_verb(argv: list[str]) -> list[str]:
    rest = argv[2:]
    while rest[:1] in (["-f"], ["-p"]):
        rest = rest[2:]
    return rest


def connected_to(monkeypatch, host: ComposeHost) -> ComposeHost:
    @contextmanager
    def connect(credentials):
        host.credentials = credentials
        yield RemoteHost(host)

    monkeypatch.setattr(CONNECT, connect)
    return host


def _listed_entries(directory: Path) -> list:
    if not directory.is_dir():
        return []
    return [
        [entry.name, entry.stat().st_size, int(entry.stat().st_mtime)]
        for entry in os.scandir(directory)
        if entry.is_file(follow_symlinks=False)
    ]

