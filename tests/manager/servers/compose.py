from __future__ import annotations

import shutil
from contextlib import contextmanager
from pathlib import Path

from dbs.manager.servers.gateways import RemoteHost
from dbs.manager.servers.services.pythons import VERSION_PROBE
from dbs.transports import RemoteResult
from tests.manager.remote import argv_of
from tests.manager.servers.support import LocalSftpSession, dbs_backup

CONNECT = "dbs.manager.servers.services.connection_service.connect"
HOST_UID = "1000"
COMPOSE_VERSION = "2.29.1"


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
    ) -> None:
        super().__init__()
        self.container = container
        self.running = running
        self.with_dbs = with_dbs
        self.container_uid = container_uid
        self.docker = docker
        self.backup_fails = backup_fails
        self.chown_fails = chown_fails
        self.owners: dict[str, str] = {}
        self.runs: list[dict] = []

    def inside(self, path: str) -> Path:
        return self.container / path.lstrip("/")

    def run(self, script, stdin_line=None, timeout=None):
        argv, setup = argv_of(script)
        self.runs.append({"argv": argv, "setup": setup, "stdin": stdin_line})
        if argv[:2] != ["docker", "compose"]:
            return RemoteResult(127, "", f"{argv[0]}: not found")
        if not self.docker:
            return RemoteResult(127, "", "sh: 1: docker: not found")
        rest = argv[2:]
        while rest[:1] == ["-f"]:
            rest = rest[2:]
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

    def exec(self, arguments: list[str], stdin_line: str | None) -> RemoteResult:
        options = {"user": self.container_uid, "env": {}}
        while arguments[0] in ("-T", "-u", "-e"):
            flag = arguments.pop(0)
            if flag == "-u":
                options["user"] = arguments.pop(0)
            elif flag == "-e":
                name, _, value = arguments.pop(0).partition("=")
                options["env"][name] = value
        service, command = arguments[0], arguments[1:]
        if service not in self.running:
            return RemoteResult(1, "", f'service "{service}" is not running')
        if command == ["id", "-u"]:
            return RemoteResult(0, f"{self.container_uid}\n", "")
        if command[:1] == ["chown"]:
            if self.chown_fails or options["user"] != "0":
                return RemoteResult(1, "", "chown: Operation not permitted")
            self.owners[command[2]] = command[1]
            return RemoteResult(0, "", "")
        if command[:2] == ["rm", "-f"]:
            path = command[2]
            owner = self.owners.get(path, self.container_uid)
            if options["user"] not in ("0", owner):
                return RemoteResult(1, "", "rm: Permission denied")
            self.inside(path).unlink(missing_ok=True)
            self.owners.pop(path, None)
            return RemoteResult(0, "", "")
        if command[1:] == ["-c", VERSION_PROBE]:
            if service in self.with_dbs and command[0] in ("python", "python3"):
                return RemoteResult(0, "0.5.0\n", "")
            return RemoteResult(127, "", f"exec: {command[0]}: not found")
        if service not in self.with_dbs:
            return RemoteResult(127, "", f"exec: {command[0]}: not found")
        return self.manage(command[2:], stdin_line, options)

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
        if command[:2] == ["dbs_key", "--show"]:
            return RemoteResult(0, "derived-passphrase-from-the-container\n", "")
        if command[:3] == ["dbs", "health", "--json"]:
            return RemoteResult(0, '{"status": "ok", "checks": []}', "")
        if command[:2] == ["migrate", "--check"]:
            return RemoteResult(0, "", "")
        if command[:1] == ["migrate"]:
            return RemoteResult(0, "No migrations to apply.", "")
        return RemoteResult(1, "", f"Unknown command: {command}")


def connected_to(monkeypatch, host: ComposeHost) -> ComposeHost:
    @contextmanager
    def connect(credentials):
        host.credentials = credentials
        yield RemoteHost(host)

    monkeypatch.setattr(CONNECT, connect)
    return host
