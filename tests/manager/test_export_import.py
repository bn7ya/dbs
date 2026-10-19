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
from dbs.manager.applications.services import ApplicationService
from dbs.manager.backups.models import BackupFile
from dbs.manager.backups.repositories import BackupFileRepository
from dbs.manager.backups.storage import BackupStorage
from dbs.manager.servers.services import ServerService

user = UserRepository().create_superuser(username="sara", password=sys.argv[1])
server = ServerService(user).create(
    name="web-1", host="10.0.0.5", username="deploy", auth_method="key",
    private_key=sys.argv[2], host_key=sys.argv[3],
)
application = ApplicationService(user).create(
    server=server.pk, name="shop", account_password=sys.argv[1], backup_passphrase="moved-passphrase",
)
storage = BackupStorage()
storage.directory(application.pk)
path = f"{application.pk}/nightly.dbs"
with storage.writing(path) as handle:
    handle.write(b"DBS nightly")
BackupFileRepository().create(
    application=application, kind="dbs", name="nightly.dbs", size=11,
    sha256="0" * 64, storage_path=path, validation="structure_ok",
)
"""

CHECK = (
    """
import json
import django

django.setup()
from django.contrib.auth import authenticate
from dbs.manager.applications.repositories import ApplicationRepository
from dbs.manager.backups.repositories import BackupFileRepository
from dbs.manager.servers.repositories import ServerRepository
from dbs.manager.servers.services import ServerConnectionService
from dbs.models import AuditEvent

server = ServerRepository().active().get()
application = ApplicationRepository().active().get()
connections = ServerConnectionService(None)
[backup] = BackupFileRepository().all_including_deleted()
print(json.dumps({
    "key": connections.credentials(server).private_key,
    "passphrase": connections.backup_passphrase(application),
    "runs_on": application.server_id == server.pk,
    "backed_up": backup.application_id == application.pk,
    "stored_under": backup.storage_path.split("/")[0] == str(application.pk),
    "removed": backup.removed_at is not None,
    "signs_in": authenticate(username="sara", password=%r) is not None,
    "actions": sorted(set(AuditEvent.objects.values_list("action", flat=True))),
}))
"""
    % PASSWORD
)


def python(script, home, *args, **extra):
    env = clean_env(
        DBS_MANAGER_HOME=str(home),
        DJANGO_SETTINGS_MODULE="dbs.manager.settings",
        **extra,
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


def manager(*args, passphrase=EXPORT_PASSPHRASE, **extra):
    return subprocess.run(
        [sys.executable, "-m", "dbs.manager.cli", *args, "--passphrase-stdin"],
        cwd=ROOT,
        env=clean_env(**extra),
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


def checked(home, **extra):
    return json.loads(python(CHECK, home, **extra).strip().splitlines()[-1])


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
    assert (state["runs_on"], state["backed_up"], state["stored_under"]) == (
        True,
        True,
        True,
    )
    assert state["signs_in"] is True
    assert state["removed"] is False
    assert {
        "manager.export",
        "manager.import",
        "server.create",
        "application.create",
    } <= set(state["actions"])
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
            assert json.loads(response.read()) == {"step": "enroll"}
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


def test_replacing_moves_the_old_installation_aside_intact(source, tmp_path):
    export = tmp_path / "manager.dbs"
    other = tmp_path / "other"
    python(SEED, other, PASSWORD, private_key_text(), host_key_line())
    assert manager("export", str(export), "--data-dir", str(other)).returncode == 0
    old_key = (source["home"] / "keys" / "secret.key").read_text()

    replaced = manager(
        "import",
        str(export),
        "--data-dir",
        str(source["home"]),
        "--replace",
        "--yes",
    )

    assert replaced.returncode == 0, replaced.stderr
    [aside] = tmp_path.glob("first.before-import-*")
    assert str(aside) in replaced.stdout
    assert (aside / "keys" / "secret.key").read_text() == old_key
    assert checked(aside)["key"] == source["key"]
    assert checked(source["home"])["key"] != source["key"]
    assert (source["home"] / "keys" / "secret.key").read_text() == (
        other / "keys" / "secret.key"
    ).read_text()
    assert not list(tmp_path.glob("first.import-*"))
    assert not (source["home"] / "import.complete").exists()


def test_replacing_an_installation_sealed_with_another_key_needs_a_yes(
    source, tmp_path
):
    export = tmp_path / "manager.dbs"
    other = tmp_path / "other"
    python(SEED, other, PASSWORD, private_key_text(), host_key_line())
    assert manager("export", str(export), "--data-dir", str(other)).returncode == 0

    refused = manager(
        "import", str(export), "--data-dir", str(source["home"]), "--replace"
    )

    assert refused.returncode == 1 and "--yes" in refused.stderr
    assert checked(source["home"])["key"] == source["key"]
    assert not list(tmp_path.glob("first.*"))


def test_an_installation_whose_key_is_in_the_keychain_exports_and_moves(
    source, tmp_path
):
    ring = {
        "DBS_MANAGER_KEY_STORE": "keychain",
        "PYTHON_KEYRING_BACKEND": "tests.manager.fake_keyring.FileKeyring",
        "DBS_TEST_KEYRING_FILE": str(tmp_path / "ring.json"),
    }
    held = (source["home"] / "keys" / "secret.key").read_text().strip()
    export = tmp_path / "manager.dbs"
    second = tmp_path / "second"

    assert checked(source["home"], **ring)["key"] == source["key"]
    assert not (source["home"] / "keys" / "secret.key").exists()
    exported = manager("export", str(export), "--data-dir", str(source["home"]), **ring)
    imported = manager("import", str(export), "--data-dir", str(second))
    replaced = manager(
        "import",
        str(export),
        "--data-dir",
        str(source["home"]),
        "--replace",
        **ring,
    )

    assert exported.returncode == 0, exported.stderr
    assert imported.returncode == 0, imported.stderr
    assert (second / "keys" / "secret.key").read_text().strip() == held
    assert checked(second)["key"] == source["key"]
    assert replaced.returncode == 0, replaced.stderr
    [aside] = tmp_path.glob("first.before-import-*")
    assert checked(aside, **ring)["key"] == source["key"]
    assert checked(source["home"], **ring)["key"] == source["key"]
    assert not (source["home"] / "keys" / "secret.key").exists()
    entries = json.loads((tmp_path / "ring.json").read_text())
    assert sorted(entries.values()) == [held, held]


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
    assert not second.exists()
    assert not list(tmp_path.glob("second.*"))


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


@pytest.mark.django_db(transaction=True)
def test_an_export_row_carries_its_size_and_digest_and_keeps_the_chain_intact(tmp_path):
    from dbs import audit
    from dbs.io import file_digest
    from dbs.manager import transfer
    from dbs.models import AuditEvent

    output = tmp_path / "manager.dbs"

    summary = transfer.export_manager(output, EXPORT_PASSPHRASE)

    event = AuditEvent.objects.get(action=transfer.EXPORT)
    size, digest = file_digest(output)
    assert event.data["size"] == summary.bytes_written == size
    assert event.data["sha256"] == summary.sha256 == digest
    assert event.chain_index is not None
    assert audit.verify_chain().intact
