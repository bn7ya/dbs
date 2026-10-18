from __future__ import annotations

import logging
import sqlite3
import stat
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.utils import ConnectionHandler
from django.test.utils import override_settings

from dbs import write_backup
from dbs.crypto.kdf import KDFParams
from dbs.manager import legacy
from dbs.manager.applications.models import Application
from dbs.manager.backups.models import BackupFile, BackupPlan
from dbs.manager.backups.storage import BackupStorage
from dbs.manager.envfiles.models import EnvVersion
from dbs.manager.envfiles.services import vault_contexts as env_contexts
from dbs.manager.servers.models import Server
from dbs.manager.servers.services import ServerConnectionService, vault_contexts
from dbs.manager.transfer import import_manager
from dbs.manager.vault import fingerprint, seal, seal_text, unseal
from tests.manager.servers.support import host_key_line, private_key_text

OLD = ("dbs_manager", "0007_server_connection_state")
SERVER_ID = "5b0e8d6a-4c64-4f7e-9d0f-0f3c2b1d7a11"
USER_ID = 7
EXPORT_PASSPHRASE = "a-long-export-passphrase"
FAST = KDFParams(time_cost=1, memory_cost=8, parallelism=1)
SSH_PASSWORD = "ssh-password-6d1f0c2e"
WEB_PASSPHRASE = "web-backup-passphrase"
SHOP_PASSPHRASE = "shop-backup-passphrase"
ENV_CONTENT = b"SECRET_KEY=kept\n"
ONLY_SQLITE = pytest.mark.skipif(
    connection.vendor != "sqlite",
    reason="These tests copy the test database into a SQLite file, and this run's "
    "test database is not SQLite.",
)


def old_server(**fields):
    values = {
        "name": "web-1",
        "created_by": USER_ID,
        "created_at": "2026-09-01T03:00:00Z",
        "updated_at": "2026-09-02T03:00:00Z",
        "deleted_at": None,
        "host": "10.0.0.5",
        "port": 2222,
        "username": "deploy",
        "auth_method": "key",
        "private_key_sealed": "c2VhbGVkLWtleQ==",
        "key_passphrase_sealed": None,
        "password_sealed": None,
        "host_key": "ssh-ed25519 AAAA",
        "host_key_fingerprint": "SHA256:web",
        "project_dir": "/srv/app",
        "python_path": "/srv/app/.venv/bin/python",
        "manage_path": "manage.py",
        "settings_module": "shop.settings.prod",
        "remote_backup_dir": "/var/backups/web",
        "backup_passphrase_sealed": "c2VhbGVkLXBhc3NwaHJhc2U=",
        "file_roots": ["/srv/app/media"],
        "env_path": "/srv/app/.env",
        "last_check_status": "ok",
        "last_check_error": "",
        "last_checked_at": "2026-09-03T03:00:00Z",
        "last_check_report": {"dbs_version": "0.7.0"},
        "last_health": None,
        "compose_files": [],
        "compose_service": "",
        "runtime": "host",
        "connection_state": "online",
        "last_connection_error": "",
        "last_seen_at": "2026-09-04T03:00:00Z",
        "timeout_in_container": None,
        "timeout_on_host": True,
    }
    return {"model": legacy.SERVER, "pk": SERVER_ID, "fields": {**values, **fields}}


def test_the_application_is_loaded_right_after_the_servers():
    order = [
        "auth.user",
        legacy.SERVER,
        "dbs_manager.backupplan",
        "dbs_manager.backupfile",
    ]

    assert legacy.SplitServers().labels(order) == [
        "auth.user",
        legacy.SERVER,
        legacy.APPLICATION,
        "dbs_manager.backupplan",
        "dbs_manager.backupfile",
    ]


def test_an_order_that_already_names_applications_or_no_servers_is_kept():
    current = ["auth.user", legacy.SERVER, legacy.APPLICATION, "dbs_manager.backupplan"]
    without = ["auth.user", "dbs_manager.account"]

    assert legacy.SplitServers().labels(current) == current
    assert legacy.SplitServers().labels(without) == without


def test_an_old_server_becomes_a_server_and_an_application_with_its_id():
    record = old_server()

    server, application = legacy.SplitServers().records(record)

    assert server["model"] == legacy.SERVER
    assert str(uuid.UUID(server["pk"])) == server["pk"] != SERVER_ID
    assert server["fields"] == {
        "name": "web-1",
        "created_by": USER_ID,
        "created_at": "2026-09-01T03:00:00Z",
        "updated_at": "2026-09-02T03:00:00Z",
        "deleted_at": None,
        "host": "10.0.0.5",
        "port": 2222,
        "username": "deploy",
        "auth_method": "key",
        "private_key_sealed": "c2VhbGVkLWtleQ==",
        "key_passphrase_sealed": None,
        "password_sealed": None,
        "host_key": "ssh-ed25519 AAAA",
        "host_key_fingerprint": "SHA256:web",
        "timeout_on_host": True,
        "connection_state": "online",
        "last_seen_at": "2026-09-04T03:00:00Z",
        "last_connection_error": "",
    }
    assert (application["model"], application["pk"]) == (legacy.APPLICATION, SERVER_ID)
    assert application["fields"] == {
        "name": "web-1",
        "created_by": USER_ID,
        "created_at": "2026-09-01T03:00:00Z",
        "updated_at": "2026-09-02T03:00:00Z",
        "deleted_at": None,
        "project_dir": "/srv/app",
        "python_path": "/srv/app/.venv/bin/python",
        "manage_path": "manage.py",
        "settings_module": "shop.settings.prod",
        "remote_backup_dir": "/var/backups/web",
        "backup_passphrase_sealed": "c2VhbGVkLXBhc3NwaHJhc2U=",
        "file_roots": ["/srv/app/media"],
        "env_path": "/srv/app/.env",
        "last_check_status": "ok",
        "last_check_error": "",
        "last_checked_at": "2026-09-03T03:00:00Z",
        "last_check_report": {"dbs_version": "0.7.0"},
        "last_health": None,
        "compose_files": [],
        "compose_service": "",
        "timeout_in_container": None,
        "server": server["pk"],
        "kind": "host",
        "engine": "",
    }
    assert record == old_server()


def test_an_old_compose_server_becomes_a_compose_application_run_by_docker():
    record = old_server(
        runtime="compose", compose_service="web", compose_files=["compose.yaml"]
    )

    _server, application = legacy.SplitServers().records(record)

    fields = application["fields"]
    assert (fields["kind"], fields["engine"]) == ("compose", "docker")
    assert (fields["compose_service"], fields["compose_files"]) == (
        "web",
        ["compose.yaml"],
    )
    assert "runtime" not in fields


def test_a_server_exported_before_the_runtime_field_existed_is_split_too():
    fields = {
        name: value
        for name, value in old_server()["fields"].items()
        if name not in ("runtime", "compose_files", "compose_service")
    }

    server, application = legacy.SplitServers().records(
        {"model": legacy.SERVER, "pk": SERVER_ID, "fields": fields}
    )

    assert server["model"] == legacy.SERVER and application["pk"] == SERVER_ID
    assert application["fields"]["kind"] == "host"
    assert application["fields"]["python_path"] == "/srv/app/.venv/bin/python"


def test_each_old_server_gets_a_server_of_its_own():
    first, _ = legacy.SplitServers().records(old_server())
    second, _ = legacy.SplitServers().records(old_server())

    assert first["pk"] != second["pk"]


@pytest.mark.parametrize(
    "label",
    ["dbs_manager.backupplan", "dbs_manager.backupfile", "dbs_manager.envversion"],
)
def test_rows_that_pointed_at_a_server_point_at_its_application(label):
    record = {"model": label, "pk": "p-1", "fields": {"name": "x", "server": SERVER_ID}}

    assert legacy.SplitServers().records(record) == [
        {"model": label, "pk": "p-1", "fields": {"name": "x", "application": SERVER_ID}}
    ]


@pytest.mark.parametrize(
    "record",
    [
        {
            "model": legacy.SERVER,
            "pk": SERVER_ID,
            "fields": {"name": "web-1", "host": "10.0.0.5", "engines": {}},
        },
        {
            "model": legacy.APPLICATION,
            "pk": SERVER_ID,
            "fields": {"name": "web-1", "server": SERVER_ID, "kind": "host"},
        },
        {
            "model": "dbs_manager.backupplan",
            "pk": "p-1",
            "fields": {"name": "nightly", "application": SERVER_ID},
        },
        {"model": "auth.user", "pk": USER_ID, "fields": {"username": "sara"}},
    ],
)
def test_records_from_0_8_pass_unchanged(record):
    assert legacy.SplitServers().records(record) == [record]


def latest():
    return MigrationExecutor(connection).loader.graph.leaf_nodes()


def migrate_to(targets):
    MigrationExecutor(connection).migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


@pytest.fixture
def old_apps():
    apps = migrate_to([OLD])
    yield apps
    migrate_to(latest())


def fill(apps):
    OldServer = apps.get_model("dbs_manager", "Server")
    OldPlan = apps.get_model("dbs_manager", "BackupPlan")
    OldFile = apps.get_model("dbs_manager", "BackupFile")
    OldEnv = apps.get_model("dbs_manager", "EnvVersion")
    sara = get_user_model().objects.create_user(username="sara", password="!")
    web = OldServer.objects.create(
        name="web-1",
        host="10.0.0.5",
        port=2222,
        username="deploy",
        auth_method="key",
        private_key_sealed=seal_text(
            private_key_text(), context=vault_contexts.PRIVATE_KEY
        ),
        host_key=host_key_line(),
        host_key_fingerprint="SHA256:web",
        project_dir="/srv/app",
        python_path="/srv/app/.venv/bin/python",
        backup_passphrase_sealed=seal_text(
            WEB_PASSPHRASE, context=vault_contexts.BACKUP_PASSPHRASE
        ),
        runtime="host",
        timeout_on_host=True,
        created_by_id=sara.pk,
    )
    shop = OldServer.objects.create(
        name="shop",
        host="10.0.0.6",
        username="root",
        auth_method="password",
        password_sealed=seal_text(SSH_PASSWORD, context=vault_contexts.PASSWORD),
        host_key=host_key_line(),
        host_key_fingerprint="SHA256:shop",
        project_dir="/srv/shop",
        backup_passphrase_sealed=seal_text(
            SHOP_PASSPHRASE, context=vault_contexts.BACKUP_PASSPHRASE
        ),
        runtime="compose",
        compose_service="web",
        compose_files=["compose.yaml"],
    )
    plans = {
        name: OldPlan.objects.create(
            server=server, name="nightly", kind="dbs", interval_minutes=1440
        )
        for name, server in (("web", web), ("shop", shop))
    }
    files = {
        name: OldFile.objects.create(
            server=server,
            plan=plans[name],
            kind="dbs",
            name=f"{server.name}.dbs",
            size=11,
            sha256="0" * 64,
            storage_path=f"{server.pk}/{server.name}.dbs",
            validation="structure_ok",
        )
        for name, server in (("web", web), ("shop", shop))
    }
    version = OldEnv.objects.create(
        server=web,
        path="/srv/app/.env",
        content_sealed=seal(ENV_CONTENT, context=env_contexts.CONTENT),
        fingerprint=fingerprint(ENV_CONTENT, context=env_contexts.CONTENT),
        size=len(ENV_CONTENT),
        key_names=["SECRET_KEY"],
        source="pulled",
    )
    return {
        "models": [get_user_model(), OldServer, OldPlan, OldFile, OldEnv],
        "web": web,
        "shop": shop,
        "plans": plans,
        "files": files,
        "version": version,
    }


def export_of_0_7(rows, folder, settings):
    keys = folder / "keys"
    backups = folder / "backups"
    keys.mkdir(parents=True)
    (keys / "secret.key").write_text(settings.SECRET_KEY)
    stored = backups / str(rows["web"].pk)
    stored.mkdir(parents=True)
    (stored / "web-1.dbs").write_bytes(b"DBS nightly")
    output = folder / "manager-0.7.dbs"
    with override_settings(DBS_FILE_ROOTS=[str(keys), str(backups)]):
        write_backup(output, EXPORT_PASSPHRASE, models=rows["models"], kdf_params=FAST)
    return output


@pytest.mark.django_db(transaction=True)
def test_a_0_7_export_imports_with_servers_and_applications_linked(
    old_apps, tmp_path, settings, data_dir
):
    rows = fill(old_apps)
    export = export_of_0_7(rows, tmp_path / "old", settings)
    migrate_to(latest())
    call_command("flush", interactive=False, verbosity=0)

    import_manager(export, EXPORT_PASSPHRASE)

    web = Application.objects.get(pk=rows["web"].pk)
    shop = Application.objects.get(pk=rows["shop"].pk)
    assert Application.objects.count() == 2
    assert Server.objects.count() == 2
    assert web.server_id != shop.server_id
    assert (web.server.name, web.server.host, web.server.port) == (
        "web-1",
        "10.0.0.5",
        2222,
    )
    assert (shop.server.host, shop.server.auth_method) == ("10.0.0.6", "password")
    assert web.server.timeout_on_host is True
    assert web.created_by.username == "sara"
    assert (web.kind, web.engine, web.project_dir) == ("host", "", "/srv/app")
    assert (shop.kind, shop.engine, shop.compose_service) == (
        "compose",
        "docker",
        "web",
    )
    connections = ServerConnectionService(None)
    assert connections.credentials(shop.server).password == SSH_PASSWORD
    assert "OPENSSH PRIVATE KEY" in connections.credentials(web.server).private_key
    assert connections.backup_passphrase(web) == WEB_PASSPHRASE
    assert connections.backup_passphrase(shop) == SHOP_PASSPHRASE
    for name, application in (("web", web), ("shop", shop)):
        plan = BackupPlan.objects.get(pk=rows["plans"][name].pk)
        file = BackupFile.all_objects.get(pk=rows["files"][name].pk)
        assert plan.application_id == application.pk
        assert (file.application_id, file.plan_id) == (application.pk, plan.pk)
        assert file.storage_path == rows["files"][name].storage_path
    version = EnvVersion.objects.get(pk=rows["version"].pk)
    assert version.application_id == web.pk
    assert unseal(version.content_sealed, context=env_contexts.CONTENT) == ENV_CONTENT
    kept = BackupFile.all_objects.get(pk=rows["files"]["web"].pk)
    missing = BackupFile.all_objects.get(pk=rows["files"]["shop"].pk)
    assert kept.removed_at is None and missing.removed_at is not None
    with BackupStorage().open_read(kept.storage_path) as handle:
        assert handle.read() == b"DBS nightly"
    assert (data_dir / "keys" / "secret.key").read_text() == settings.SECRET_KEY


def database_at(path):
    return ConnectionHandler(
        {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": str(path)}}
    )["default"]


def snapshot(path):
    connection.ensure_connection()
    target = sqlite3.connect(str(path))
    try:
        connection.connection.backup(target)
    finally:
        target.close()
    return path


@pytest.fixture
def opened(monkeypatch):
    held = []

    def open_database(path):
        database = database_at(path)
        held.append(database)
        monkeypatch.setattr("django.db.connection", database)
        return database

    yield open_database
    for database in held:
        database.close()


def rows_in(path, query):
    copy = sqlite3.connect(str(path))
    try:
        return copy.execute(query).fetchall()
    finally:
        copy.close()


@ONLY_SQLITE
@pytest.mark.django_db(transaction=True)
def test_a_database_from_0_7_is_copied_privately_before_the_split(
    old_apps, tmp_path, opened
):
    rows = fill(old_apps)
    source = snapshot(tmp_path / "manager.sqlite3")
    opened(source)

    kept = legacy.preserve_before_split()

    assert kept == tmp_path / "manager.sqlite3.pre-0.8.0"
    assert stat.S_IMODE(kept.stat().st_mode) == 0o600
    servers = "SELECT id, name, runtime FROM dbs_manager_server ORDER BY name"
    assert rows_in(kept, servers) == [
        (rows["shop"].pk.hex, "shop", "compose"),
        (rows["web"].pk.hex, "web-1", "host"),
    ]
    assert rows_in(kept, servers) == rows_in(source, servers)
    applied = rows_in(
        kept, "SELECT name FROM django_migrations WHERE app = 'dbs_manager'"
    )
    assert ("0007_server_connection_state",) in applied
    assert ("0008_application",) not in applied


@ONLY_SQLITE
@pytest.mark.django_db(transaction=True)
def test_an_existing_copy_is_never_overwritten(old_apps, tmp_path, opened):
    fill(old_apps)
    source = snapshot(tmp_path / "manager.sqlite3")
    earlier = tmp_path / "manager.sqlite3.pre-0.8.0"
    earlier.write_bytes(b"the copy kept the first time")
    opened(source)

    assert legacy.preserve_before_split() == earlier
    assert earlier.read_bytes() == b"the copy kept the first time"


@ONLY_SQLITE
@pytest.mark.django_db
def test_a_database_already_split_is_not_copied(tmp_path, opened):
    source = snapshot(tmp_path / "manager.sqlite3")
    opened(source)

    assert legacy.preserve_before_split() is None
    assert not (tmp_path / "manager.sqlite3.pre-0.8.0").exists()


@pytest.mark.django_db
def test_a_fresh_database_is_not_copied(tmp_path, opened):
    source = tmp_path / "manager.sqlite3"
    opened(source)

    assert legacy.preserve_before_split() is None
    assert not (tmp_path / "manager.sqlite3.pre-0.8.0").exists()


@ONLY_SQLITE
@pytest.mark.django_db(transaction=True)
def test_another_database_is_named_to_back_up_but_not_copied(
    old_apps, tmp_path, opened, monkeypatch, caplog
):
    fill(old_apps)
    database = opened(snapshot(tmp_path / "manager.sqlite3"))
    monkeypatch.setattr(database, "vendor", "postgresql")

    with caplog.at_level(logging.WARNING, logger="dbs.manager"):
        assert legacy.preserve_before_split() is None

    assert "keep a backup of its database" in caplog.text
    assert not (tmp_path / "manager.sqlite3.pre-0.8.0").exists()
