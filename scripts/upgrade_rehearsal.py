import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT = REPO_ROOT / "tests" / "containers" / "project"
PASSPHRASE = "rehearsal-backup-passphrase"
ACCOUNT = "admin"
ACCOUNT_PASSWORD = "rehearsal-account-password-1"
SERVER_PASSPHRASE = "rehearsal-server-passphrase"
NOTES = ("first", "second", "third")
BOOT_SECONDS = 60

SETTINGS = """from shop.settings import *  # noqa: F401,F403
import os

DATABASES = {{"default": {{"ENGINE": "django.db.backends.sqlite3", "NAME": {database!r}}}}}
DBS_BACKUP_DIR = {backups!r}
"""

OLD_SERVER = """
import django
django.setup()
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.contrib.auth import get_user_model
from dbs.manager.activity.services import ActivityService
from dbs.manager.servers.services import ServerService

key = Ed25519PrivateKey.generate()
private = key.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.OpenSSH,
    serialization.NoEncryption(),
).decode()
host = Ed25519PrivateKey.generate().public_key().public_bytes(
    serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
).decode()
user = get_user_model().objects.get(username={account!r})
server = ServerService(user).create(
    name="web-1",
    host="192.0.2.10",
    port=22,
    username="deploy",
    auth_method="key",
    private_key=private,
    host_key=host,
    project_dir="/srv/shop",
    python_path="/srv/shop/.venv/bin/python",
    remote_backup_dir="/var/backups/dbs",
    env_path="/srv/shop/.env",
    backup_passphrase={passphrase!r},
)
print(server.pk)
"""

NEW_MANAGER = """
import json
import django
django.setup()
from dbs import audit
from dbs.manager.applications.models import Application
from dbs.manager.servers.models import Server
from dbs.manager.servers.services import ServerConnectionService

application = Application.objects.get()
print(json.dumps({{
    "application": str(application.pk),
    "server_count": Server.objects.count(),
    "server_host": application.server.host,
    "project_dir": application.project_dir,
    "kind": application.kind,
    "passphrase": ServerConnectionService(None).backup_passphrase(application) == {passphrase!r},
    "chain_intact": audit.verify_chain().intact,
}}))
"""


class RehearsalFailed(Exception):
    pass


def arguments(argv=None):
    parser = argparse.ArgumentParser(
        description="Install django-dbs 0.7.0 from PyPI, fill a project and a manager, "
        "upgrade both to this checkout and check that nothing was lost."
    )
    parser.add_argument("--from-version", default="0.7.0")
    parser.add_argument("--work", default="", help="A folder to work in; a new one by default.")
    parser.add_argument("--keep", action="store_true", help="Leave the work folder behind.")
    return parser.parse_args(argv)


class Rehearsal:
    def __init__(self, work: Path, from_version: str) -> None:
        self.work = work
        self.from_version = from_version
        self.venv = work / "venv"
        self.project = work / "project"
        self.data = work / "data"
        self.backups = work / "backups"
        self.manager = work / "manager"
        self.env = {
            **os.environ,
            "DJANGO_SETTINGS_MODULE": "shop.rehearsal_settings",
            "DBS_MANAGER_KEY_STORE": "file",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        self.env.pop("DBS_MANAGER_DATABASE_URL", None)

    def say(self, message: str) -> None:
        print(f"* {message}", flush=True)

    def run(self, *command, stdin: str | None = None, cwd: Path | None = None, env=None):
        done = subprocess.run(
            [str(part) for part in command],
            input=stdin,
            capture_output=True,
            text=True,
            cwd=cwd or self.project,
            env=env or self.env,
        )
        if done.returncode != 0:
            raise RehearsalFailed(
                f"{' '.join(map(str, command))} exited {done.returncode}\n"
                f"{done.stdout[-3000:]}\n{done.stderr[-3000:]}"
            )
        return done.stdout

    def python(self, *arguments, **options):
        return self.run(self.venv / "bin" / "python", *arguments, **options)

    def manage(self, *arguments, **options):
        return self.python("manage.py", *arguments, **options)

    def manager_cli(self, *arguments, **options):
        return self.run(
            self.venv / "bin" / "django_dbs",
            *arguments,
            "--data-dir",
            self.manager,
            cwd=self.work,
            **options,
        )

    def manager_python(self, code: str) -> str:
        env = {
            **self.env,
            "DJANGO_SETTINGS_MODULE": "dbs.manager.settings",
            "DBS_MANAGER_HOME": str(self.manager),
        }
        return self.python("-c", code, cwd=self.work, env=env)

    def notes(self) -> list[str]:
        printed = self.python(
            "-c",
            "import django; django.setup(); from notes.models import Note; "
            "print(','.join(Note.objects.order_by('pk').values_list('title', flat=True)))",
        )
        return [title for title in printed.strip().split(",") if title]

    def expect(self, condition: bool, message: str) -> None:
        if not condition:
            raise RehearsalFailed(message)

    def prepare(self) -> None:
        self.say(f"installing django-dbs {self.from_version} from PyPI")
        subprocess.run([sys.executable, "-m", "venv", str(self.venv)], check=True)
        self.run(
            self.venv / "bin" / "pip",
            "install",
            "--quiet",
            f"django-dbs[manager]=={self.from_version}",
            cwd=self.work,
        )
        shutil.copytree(PROJECT, self.project)
        self.data.mkdir()
        self.backups.mkdir(mode=0o700)
        (self.project / "shop" / "rehearsal_settings.py").write_text(
            SETTINGS.format(
                database=str(self.data / "db.sqlite3"), backups=str(self.backups)
            ),
            encoding="utf-8",
        )

    def fill(self) -> tuple[Path, str]:
        self.say(f"filling a project with {self.from_version}")
        self.manage("migrate", "--noinput")
        self.python(
            "-c",
            "import django; django.setup(); from notes.models import Note; "
            + "; ".join(f"Note.objects.create(title={title!r})" for title in NOTES),
        )
        old_backup = self.work / "before-upgrade.dbs"
        self.manage("dbs_backup", old_backup, "--passphrase-stdin", stdin=f"{PASSPHRASE}\n")
        self.say(f"filling a manager with {self.from_version}")
        self.manager_cli(
            "createuser", ACCOUNT, "--password-stdin", stdin=f"{ACCOUNT_PASSWORD}\n"
        )
        server_id = self.manager_python(
            OLD_SERVER.format(account=ACCOUNT, passphrase=SERVER_PASSPHRASE)
        ).strip().splitlines()[-1]
        return old_backup, server_id

    def upgrade(self) -> None:
        self.say("upgrading to this checkout")
        wheels = self.work / "wheel"
        self.run(
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--quiet",
            "--no-deps",
            "--wheel-dir",
            wheels,
            REPO_ROOT,
            cwd=self.work,
        )
        [wheel] = wheels.glob("django_dbs-*.whl")
        self.run(self.venv / "bin" / "pip", "install", "--quiet", wheel, cwd=self.work)

    def check_project(self, old_backup: Path) -> None:
        self.say("checking the project")
        self.manage("migrate", "--noinput")
        report = self.run(
            self.venv / "bin" / "python",
            "manage.py",
            "dbs",
            "upgrade",
            "--check",
            "--offline",
            "--backups",
            self.backups,
        )
        print(report, end="")
        self.manage("dbs_validate", old_backup, "--passphrase-stdin", stdin=f"{PASSPHRASE}\n")
        self.python(
            "-c",
            "import django; django.setup(); from notes.models import Note; "
            "Note.objects.all().delete(); Note.objects.create(title='after')",
        )
        self.manage(
            "dbs_restore", old_backup, "--flush", "--passphrase-stdin", stdin=f"{PASSPHRASE}\n"
        )
        self.expect(
            self.notes() == list(NOTES),
            f"the {self.from_version} backup restored {self.notes()}, not {list(NOTES)}",
        )
        new_backup = self.work / "after-upgrade.dbs"
        self.manage("dbs_backup", new_backup, "--passphrase-stdin", stdin=f"{PASSPHRASE}\n")
        self.manage("dbs_validate", new_backup, "--passphrase-stdin", stdin=f"{PASSPHRASE}\n")

    def check_manager(self, server_id: str) -> None:
        self.say("checking the manager")
        listed = json.loads(self.manager_cli("app", "list", "--json", "--as", ACCOUNT))
        self.expect(
            [row["id"] for row in listed] == [server_id],
            f"the applications after the upgrade are {listed}, not the old server {server_id}",
        )
        found = json.loads(
            self.manager_python(NEW_MANAGER.format(passphrase=SERVER_PASSPHRASE))
            .strip()
            .splitlines()[-1]
        )
        self.expect(found["server_count"] == 1, f"expected one server: {found}")
        self.expect(found["server_host"] == "192.0.2.10", f"the server moved: {found}")
        self.expect(found["project_dir"] == "/srv/shop", f"the project moved: {found}")
        self.expect(found["passphrase"], "the backup passphrase no longer unseals")
        self.expect(found["chain_intact"], "the audit chain is broken")
        kept = list(self.manager.glob("*.pre-0.8.0"))
        self.expect(bool(kept), "no copy of the manager's database from before 0.8.0")

    def boot(self) -> None:
        self.say("starting the upgraded manager")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        running = subprocess.Popen(
            [
                str(self.venv / "bin" / "django_dbs"),
                "run",
                "--no-browser",
                "--port",
                str(port),
                "--data-dir",
                str(self.manager),
            ],
            cwd=self.work,
            env=self.env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + BOOT_SECONDS
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            while True:
                try:
                    with opener.open(f"http://127.0.0.1:{port}/api/health/", timeout=5) as answer:
                        self.expect(answer.status == 200, f"health answered {answer.status}")
                        return
                except OSError:
                    if running.poll() is not None or time.monotonic() > deadline:
                        raise RehearsalFailed(
                            f"the manager did not answer: {running.stderr.read()[-2000:]}"
                        ) from None
                    time.sleep(1)
        finally:
            running.terminate()
            running.wait(30)

    def run_all(self) -> None:
        self.prepare()
        old_backup, server_id = self.fill()
        self.upgrade()
        self.check_project(old_backup)
        self.check_manager(server_id)
        self.boot()


def main(argv=None):
    options = arguments(argv)
    work = Path(options.work or tempfile.mkdtemp(prefix="dbs-upgrade-"))
    work.mkdir(parents=True, exist_ok=True)
    try:
        Rehearsal(work, options.from_version).run_all()
    except RehearsalFailed as exc:
        print(f"Upgrade rehearsal failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if not options.keep:
            shutil.rmtree(work, ignore_errors=True)
    print(f"Upgraded {options.from_version} to this checkout: nothing was lost.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
