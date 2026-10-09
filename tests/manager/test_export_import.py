import json
import subprocess
import sys
import urllib.request

import pytest

from tests.manager.servers.support import host_key_line, private_key_text
from tests.manager.test_cli import ROOT, Running, clean_env

PASSWORD = "correct-horse-battery-staple"
EXPORT_PASSPHRASE = "a-long-export-passphrase"
TIMEOUT = 120

SEED = """
import io, sys
import django
from django.core.management import call_command

django.setup()
call_command("migrate", verbosity=0)
from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.backups.models import BackupFile
from dbs.manager.backups.repositories import BackupFileRepository
from dbs.manager.backups.storage import BackupStorage
from dbs.manager.servers.services import ServerService

user = UserRepository().create_superuser(username="sara", password=sys.argv[1])
server = ServerService(user).create(
    name="web-1", host="10.0.0.5", username="deploy", auth_method="key",
    private_key=sys.argv[2], host_key=sys.argv[3], backup_passphrase="moved-passphrase",
)
storage = BackupStorage()
storage.directory(server.pk)
path = f"{server.pk}/nightly.dbs"
with storage.writing(path) as handle:
    handle.write(b"DBS nightly")
BackupFileRepository().create(
    server=server, kind="dbs", name="nightly.dbs", size=11, sha256="0" * 64,
    storage_path=path, validation="structure_ok",
)
"""

CHECK = (
    """
import json
import django

django.setup()
from django.contrib.auth import authenticate
from dbs.manager.backups.repositories import BackupFileRepository
from dbs.manager.servers.repositories import ServerRepository
from dbs.manager.servers.services import ServerConnectionService
from dbs.models import AuditEvent

server = ServerRepository().active().get()
connections = ServerConnectionService(None)
[backup] = BackupFileRepository().all_including_deleted()
print(json.dumps({
    "key": connections.credentials(server).private_key,
    "passphrase": connections.backup_passphrase(server),
    "removed": backup.removed_at is not None,
    "signs_in": authenticate(username="sara", password=%r) is not None,
    "actions": sorted(set(AuditEvent.objects.values_list("action", flat=True))),
}))
"""
    % PASSWORD
)


def python(script, home, *args):
    env = clean_env(
        DBS_MANAGER_HOME=str(home), DJANGO_SETTINGS_MODULE="dbs.manager.settings"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def manager(*args, passphrase=EXPORT_PASSPHRASE):
    return subprocess.run(
        [sys.executable, "-m", "dbs.manager.cli", *args, "--passphrase-stdin"],
        cwd=ROOT,
        env=clean_env(),
        input=f"{passphrase}\n",
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )


@pytest.fixture
def source(tmp_path):
    home = tmp_path / "first"
    private_key = private_key_text()
    python(SEED, home, PASSWORD, private_key, host_key_line())
    return {"home": home, "key": private_key}


def checked(home):
    return json.loads(python(CHECK, home).strip().splitlines()[-1])


def test_an_export_moves_the_manager_to_another_data_directory(source, tmp_path):
    export = tmp_path / "manager.dbs"
    second = tmp_path / "second"

    exported = manager(
        "export", str(export), "--with-backups", "--data-dir", str(source["home"])
    )
    imported = manager("import", str(export), "--data-dir", str(second))

    assert exported.returncode == 0, exported.stderr
    assert imported.returncode == 0, imported.stderr
    assert (second / "keys" / "secret.key").read_text() == (
        source["home"] / "keys" / "secret.key"
    ).read_text()
    assert (second / "keys" / "secret.key").stat().st_mode & 0o777 == 0o600
    state = checked(second)
    assert state["key"] == source["key"]
    assert state["passphrase"] == "moved-passphrase"
    assert state["signs_in"] is True
    assert state["removed"] is False
    assert {"manager.export", "manager.import", "server.create"} <= set(
        state["actions"]
    )
    assert list((second / "backups").glob("*/nightly.dbs"))


def test_the_imported_account_signs_in_over_http(source, tmp_path):
    export = tmp_path / "manager.dbs"
    second = tmp_path / "second"
    assert (
        manager("export", str(export), "--data-dir", str(source["home"])).returncode
        == 0
    )
    assert manager("import", str(export), "--data-dir", str(second)).returncode == 0

    running = Running(second)
    try:
        assert running.url == f"{running.base}/"
        request = urllib.request.Request(
            f"{running.base}/api/auth/login/",
            data=json.dumps({"username": "sara", "password": PASSWORD}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=10) as response:
            assert response.status == 200
            assert json.loads(response.read())["username"] == "sara"
    finally:
        running.stop()


def test_backups_left_out_of_the_export_are_marked_removed(source, tmp_path):
    export = tmp_path / "manager.dbs"
    second = tmp_path / "second"
    assert (
        manager("export", str(export), "--data-dir", str(source["home"])).returncode
        == 0
    )
    assert manager("import", str(export), "--data-dir", str(second)).returncode == 0

    assert checked(second)["removed"] is True


def test_an_import_refuses_a_directory_that_already_manages_servers(source, tmp_path):
    export = tmp_path / "manager.dbs"
    assert (
        manager("export", str(export), "--data-dir", str(source["home"])).returncode
        == 0
    )

    refused = manager("import", str(export), "--data-dir", str(source["home"]))
    replaced = manager(
        "import", str(export), "--data-dir", str(source["home"]), "--replace"
    )

    assert refused.returncode == 1 and "--replace" in refused.stderr
    assert replaced.returncode == 0, replaced.stderr
    assert checked(source["home"])["signs_in"] is True


def test_an_import_refuses_while_the_manager_runs(source, tmp_path):
    export = tmp_path / "manager.dbs"
    second = tmp_path / "second"
    assert (
        manager("export", str(export), "--data-dir", str(source["home"])).returncode
        == 0
    )
    running = Running(second)
    try:
        refused = manager("import", str(export), "--data-dir", str(second))
    finally:
        running.stop()

    assert refused.returncode == 1
    assert "stop it first" in refused.stderr


def test_a_wrong_passphrase_imports_nothing(source, tmp_path):
    export = tmp_path / "manager.dbs"
    second = tmp_path / "second"
    assert (
        manager("export", str(export), "--data-dir", str(source["home"])).returncode
        == 0
    )

    refused = manager(
        "import",
        str(export),
        "--data-dir",
        str(second),
        passphrase="not-the-passphrase",
    )

    assert refused.returncode == 1
    assert not (second / "backups").exists()


def test_an_export_never_overwrites_a_file_and_needs_a_long_passphrase(
    source, tmp_path
):
    export = tmp_path / "manager.dbs"
    export.write_bytes(b"keep me")

    existing = manager("export", str(export), "--data-dir", str(source["home"]))
    short = manager(
        "export",
        str(tmp_path / "other.dbs"),
        "--data-dir",
        str(source["home"]),
        passphrase="short",
    )

    assert existing.returncode == 1 and "already exists" in existing.stderr
    assert export.read_bytes() == b"keep me"
    assert short.returncode == 1 and "12 characters" in short.stderr
    assert not (tmp_path / "other.dbs").exists()
