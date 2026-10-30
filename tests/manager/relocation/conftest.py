from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from dbs.manager.applications.services.facts import DATABASE_FACTS, FACTS_MARKER
from dbs.manager.relocation import inventory
from dbs.manager.servers.services.pythons import VERSION_PROBE
from dbs.naming import backup_filename
from tests.manager.factories import make_application, make_server
from tests.manager.relocation.hosts import LocalSource, LocalTarget, unwrap
from tests.manager.remote import scripted_hosts
from tests.manager.servers.support import BACKUP_PASSPHRASE, DBS_VERSION, dbs_backup

SOURCE = "10.0.0.5"
TARGET = "10.0.0.6"
SUDO_PASSWORD = "sudo-secret-9d2c41"
UBUNTU = 'ID=ubuntu\nVERSION_ID="24.04"\nVERSION_CODENAME=noble\n'
TOKENS = (
    "id",
    "sudo",
    "uname",
    "getenforce",
    "docker",
    "podman",
    "du",
    "find",
    "git",
    "ss",
    "df",
    "systemctl",
    "dpkg-query",
    "tar",
    "sha256sum",
    "true",
    "mysql",
    "timeout",
)


def version_of(argv):
    return argv[1:3] == ["-c", inventory.PYTHON_VERSION]


class Host:
    def __init__(self, world, name, uid, user):
        self.world = world
        self.name = name
        self.uid = uid
        self.user = user
        self.runs = []

    def __call__(self, argv, line):
        self.runs.append({"argv": list(argv), "line": line})
        if list(argv) == ["sudo", "-n", "-k", "--", "true"]:
            return 1, "", "sudo: a password is required\n"
        if list(argv[:2]) == ["sudo", "-S"] and line != SUDO_PASSWORD:
            return 1, "", "Sorry, try again.\nsudo: 1 incorrect password attempt\n"
        bare = unwrap(argv)
        answer = self.answer(bare, line)
        if answer is None:
            return 127, "", f"{bare[0]}: not found"
        return answer

    def answer(self, argv, line):
        name = argv[0]
        if name == "id" and len(argv) == 1:
            return 0, f"uid={self.uid}({self.user}) gid={self.uid}({self.user})\n", ""
        if argv == ["sudo", "--version"]:
            return 0, "Sudo version 1.9.15\n", ""
        if argv == ["true"]:
            return 0, "", ""
        if argv == ["uname", "-m"]:
            return 0, "x86_64\n", ""
        if argv == ["uname", "-sr"]:
            return 0, "Linux 6.8\n", ""
        if name == "systemctl" and argv[1:] == ["is-active", "firewalld"]:
            return 3, "inactive\n", ""
        if name == "ss":
            return 0, "", ""
        if name == "df":
            lines = ["Filesystem 1-blocks Used Available Capacity Mounted on"]
            lines += ["/dev/sda1 1000000000000 1 900000000000 1% /" for _ in argv[4:]]
            return 0, "\n".join(lines) + "\n", ""
        if name == "du":
            return 0, f"4096\t{argv[-1]}\n", ""
        if name == "find":
            return 0, "", ""
        return None


class SourceHost(Host):
    def answer(self, argv, line):
        found = super().answer(argv, line)
        if found is not None:
            return found
        world = self.world
        if argv[:2] == ["tar", "--create"]:
            return world["reader"](argv, line)
        if argv[0] == "git":
            return world["git"](argv)
        if argv[0] == world["python"]:
            return world["source_python"](argv, line)
        return None


class TargetHost(Host):
    def answer(self, argv, line):
        found = super().answer(argv, line)
        if found is not None:
            return found
        world = self.world
        if argv[0] == "dpkg-query":
            names = argv[4:]
            return 0, "".join(f"{name}\tii \n" for name in names), ""
        if argv[0] == "env" and "apt-get" in argv:
            world["apt"].append(argv)
            return 0, "", ""
        if argv[0] == "git":
            return world["git"](argv)
        if argv[0] in ("/usr/bin/python3", "python3") and version_of(argv):
            return 0, "3.12\n", ""
        if argv[0] == "/usr/bin/python3" and argv[1:3] == ["-m", "venv"]:
            venv = Path(argv[3])
            (venv / "bin").mkdir(parents=True)
            (venv / "bin" / "python").write_text("")
            return 0, "", ""
        if argv[0] == world["target_python"]:
            return world["target_python_answer"](argv, line)
        local = world["local_target"](argv, line)
        if local[0] != 127:
            return local
        return None


def streamed_backup(world):
    def stream(argv, line):
        made = dbs_backup(line)
        prefix = argv[argv.index("--prefix") + 1]
        folder = Path(argv[argv.index("--output-dir") + 1])
        folder.mkdir(parents=True, exist_ok=True)
        name = backup_filename(prefix)
        (folder / name).write_bytes(made)
        world["taken"].append(name)
        summary = {"name": name, "size": len(made), "sha256": hashlib.sha256(made).hexdigest()}
        return 0, made, json.dumps(summary)

    return stream


@pytest.fixture
def world(admin, tmp_path, monkeypatch, settings):
    settings.DBS_MANAGER_JOBS_INLINE = True
    os_release = tmp_path / "os-release"
    os_release.write_text(UBUNTU)
    monkeypatch.setattr(inventory, "OS_RELEASE", str(os_release))
    source_root = tmp_path / "source"
    project = source_root / "srv" / "shop"
    (project / ".git").mkdir(parents=True)
    (project / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (project / "manage.py").write_text(
        'os.environ.setdefault("DJANGO_SETTINGS_MODULE", "shop.settings")\n'
    )
    (project / ".env").write_text("SECRET_KEY=moving\n")
    (project / "db.sqlite3").write_text("live rows\n")
    (project / ".venv" / "bin").mkdir(parents=True)
    (project / ".venv" / "bin" / "python").write_text("")
    backups = tmp_path / "backups"
    backups.mkdir()
    target_folder = tmp_path / "target" / "srv" / "shop"
    target_folder.parent.mkdir(parents=True)
    for folder in (tmp_path, source_root, project.parent, target_folder.parent, tmp_path / "target"):
        os.chmod(folder, 0o755)
    python = str(project / ".venv" / "bin" / "python")
    target_python = str(target_folder / ".venv" / "bin" / "python")
    hosts = scripted_hosts(monkeypatch)
    state: dict = {
        "python": python,
        "target_python": target_python,
        "taken": [],
        "apt": [],
        "restores": [],
        "migrations": 0,
        "project": project,
        "target_folder": target_folder,
        "backups": backups,
    }
    source_reader = LocalSource()
    local_target = LocalTarget()
    local_target.root = str(tmp_path / "target")
    state["reader"] = source_reader
    state["local_target"] = local_target

    def git(argv):
        command = argv[3:]
        if command == ["rev-parse", "HEAD"]:
            return 0, "a" * 40 + "\n", ""
        if command == ["rev-parse", "--abbrev-ref", "HEAD"]:
            return 0, "main\n", ""
        if command == ["remote", "get-url", "origin"]:
            return 0, "https://token123@github.com/org/shop.git\n", ""
        if command == ["status", "--porcelain"]:
            return 0, "", ""
        return 1, "", ""

    def facts_for(folder):
        return 0, FACTS_MARKER + json.dumps(
            {
                "vendor": "sqlite",
                "engine": "django.db.backends.sqlite3",
                "host": "",
                "port": "",
                "name": f"{folder}/db.sqlite3",
                "user": "",
                "caches": [],
                "broker": None,
            }
        ) + "\n", ""

    def source_python(argv, line):
        if version_of(argv):
            return 0, "3.12\n", ""
        if argv[1:5] == ["-m", "pip", "list", "--format=json"]:
            return 0, json.dumps([{"name": "Django", "version": "5.2"}, {"name": "django-dbs", "version": "0.8.0"}]), ""
        if argv[1:3] == ["-m", "pip"]:
            return 0, "Django==5.2\ndjango-dbs @ file:///gone/django_dbs-0.8.0-py3-none-any.whl\n", ""
        if argv[1:] == ["manage.py", "shell", "-c", DATABASE_FACTS]:
            return facts_for(project)
        if argv[1:4] == ["manage.py", "dbs_backup", "--stream"]:
            return streamed_backup(state)(argv, line)
        return None

    def target_python_answer(argv, line):
        if argv[1:] == ["-c", VERSION_PROBE] or argv[1:] == ["-c", DBS_VERSION]:
            return 0, "0.8.0\n", ""
        if version_of(argv):
            return 0, "3.12\n", ""
        if argv[1:3] == ["-m", "pip"]:
            state["pip"] = Path(argv[-1]).read_text()
            return 0, "", ""
        if argv[1:] == ["manage.py", "shell", "-c", DATABASE_FACTS]:
            return facts_for(target_folder)
        if argv[1:] == ["manage.py", "dbs", "connection", "--json"]:
            return 0, json.dumps(
                {
                    "dbs_connection": 2,
                    "settings_module": "shop.settings",
                    "remote_backup_dir": str(backups),
                    "file_roots": [],
                    "env_path": str(target_folder / ".env"),
                    "dbs_version": "0.8.0",
                }
            ), ""
        if argv[1:] == ["manage.py", "migrate", "--noinput"]:
            state["migrations"] += 1
            return 0, "No migrations to apply.\n", ""
        if argv[1:3] == ["manage.py", "dbs_restore"]:
            state["restores"].append({"argv": argv, "line": line, "data": Path(argv[3]).read_bytes()})
            return 0, "Restored 12 records and 0 files\n", ""
        if argv[1:] == ["manage.py", "dbs_backup", "--help"]:
            return 0, "usage\n", ""
        if argv[1:] == ["manage.py", "dbs", "health", "--json"]:
            return 1, "", ""
        return None

    state["git"] = git
    state["source_python"] = source_python
    state["target_python_answer"] = target_python_answer
    source_host = SourceHost(state, SOURCE, "1001", "deploy")
    target_host = TargetHost(state, TARGET, "1000", "ubuntu")
    for token in (*TOKENS, python):
        hosts.answer(SOURCE, [token], source_host)
    for token in (*TOKENS, "env", "install", "mv", "rmdir", "chown", "/usr/bin/python3", "python3", target_python):
        hosts.answer(TARGET, [token], target_host)
    source_server = make_server(admin, name="old", host=SOURCE)
    target_server = make_server(admin, name="new", host=TARGET)
    application = make_application(
        admin,
        "shop",
        server=source_server,
        project_dir=str(project),
        python_path=python,
        settings_module="shop.settings",
        remote_backup_dir=str(backups),
        env_path=str(project / ".env"),
        backup_passphrase=BACKUP_PASSPHRASE,
        deployment={"runs_in": "host", "database": "sqlite"},
    )
    state.update(
        {
            "hosts": hosts,
            "source_host": source_host,
            "target_host": target_host,
            "source_server": source_server,
            "target_server": target_server,
            "application": application,
        }
    )
    return state
