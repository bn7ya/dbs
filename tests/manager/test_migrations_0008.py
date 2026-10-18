from __future__ import annotations

import io
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from dbs import audit
from dbs.manager.applications.models import Application
from dbs.manager.backups.models import BackupFile, BackupPlan
from dbs.manager.envfiles.models import EnvVersion
from dbs.manager.envfiles.services import vault_contexts as env_contexts
from dbs.manager.servers.models import Server
from dbs.manager.servers.services import vault_contexts
from dbs.manager.vault import fingerprint, seal, seal_text, unseal, unseal_text
from tests.manager.servers.support import host_key_line, private_key_text
from tests.manager.support import Logged

OLD = ("dbs_manager", "0007_server_connection_state")
SSH_FIELDS = (
    "host",
    "port",
    "username",
    "auth_method",
    "private_key_sealed",
    "key_passphrase_sealed",
    "password_sealed",
    "host_key",
    "host_key_fingerprint",
    "timeout_on_host",
    "connection_state",
    "last_seen_at",
    "last_connection_error",
)
PRIVATE_KEY = private_key_text()
HOST_KEY = host_key_line()
KEY_PASSPHRASE = "key-passphrase-93ab7e"
SSH_PASSWORD = "ssh-password-6d1f0c2e"
WEB_PASSPHRASE = "web-backup-passphrase"
SHOP_PASSPHRASE = "shop-backup-passphrase"
ENV_CONTENT = b"SECRET_KEY=kept\n"


def latest():
    return MigrationExecutor(connection).loader.graph.leaf_nodes()


def migrate_to(targets):
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


@pytest.fixture
def old_apps():
    apps = migrate_to([OLD])
    yield apps
    migrate_to(latest())


def plain(value):
    return bytes(value) if isinstance(value, (bytes, memoryview)) else value


def columns(row):
    return {field: plain(getattr(row, field)) for field in SSH_FIELDS}


def fill(apps):
    User = apps.get_model("auth", "User")
    OldServer = apps.get_model("dbs_manager", "Server")
    OldPlan = apps.get_model("dbs_manager", "BackupPlan")
    OldFile = apps.get_model("dbs_manager", "BackupFile")
    OldEnv = apps.get_model("dbs_manager", "EnvVersion")
    now = timezone.now()
    sara = User.objects.create(username="sara", password="!")
    web = OldServer.objects.create(
        name="web-1",
        host="10.0.0.5",
        port=2222,
        username="deploy",
        auth_method="key",
        private_key_sealed=seal_text(PRIVATE_KEY, context=vault_contexts.PRIVATE_KEY),
        key_passphrase_sealed=seal_text(
            KEY_PASSPHRASE, context=vault_contexts.KEY_PASSPHRASE
        ),
        host_key=HOST_KEY,
        host_key_fingerprint="SHA256:web",
        project_dir="/srv/app",
        python_path="/srv/app/.venv/bin/python",
        settings_module="shop.settings.prod",
        remote_backup_dir="/var/backups/web",
        backup_passphrase_sealed=seal_text(
            WEB_PASSPHRASE, context=vault_contexts.BACKUP_PASSPHRASE
        ),
        file_roots=["/srv/app/media"],
        env_path="/srv/app/.env",
        last_check_status="ok",
        last_health={"status": "ok"},
        timeout_on_host=True,
        connection_state="online",
        last_seen_at=now,
        runtime="host",
        created_by=sara,
    )
    shop = OldServer.objects.create(
        name="shop",
        host="10.0.0.6",
        username="root",
        auth_method="password",
        password_sealed=seal_text(SSH_PASSWORD, context=vault_contexts.PASSWORD),
        host_key=HOST_KEY,
        host_key_fingerprint="SHA256:shop",
        project_dir="/srv/shop",
        python_path="python",
        backup_passphrase_sealed=seal_text(
            SHOP_PASSPHRASE, context=vault_contexts.BACKUP_PASSPHRASE
        ),
        runtime="compose",
        compose_service="web",
        compose_files=["compose.yaml", "compose.prod.yaml"],
        timeout_in_container=True,
        connection_state="offline",
        last_connection_error="ssh_unreachable",
    )
    retired = OldServer.objects.create(
        name="web-1",
        host="10.0.0.9",
        username="deploy",
        auth_method="key",
        host_key=HOST_KEY,
        host_key_fingerprint="SHA256:retired",
        deleted_at=now - timedelta(days=3),
    )
    OldServer.objects.filter(pk=web.pk).update(created_at=now - timedelta(days=40))
    plans = {
        name: OldPlan.objects.create(
            server=server, name="nightly", kind="dbs", interval_minutes=1440
        )
        for name, server in (("web", web), ("shop", shop))
    }
    files = [
        OldFile.objects.create(
            server=server,
            plan=plan,
            kind="dbs",
            name=f"{server.name}.dbs",
            size=11,
            sha256="0" * 64,
            storage_path=f"{server.pk}/{server.name}.dbs",
            validation="structure_ok",
        )
        for server, plan in (
            (web, plans["web"]),
            (shop, plans["shop"]),
            (retired, None),
        )
    ]
    version = OldEnv.objects.create(
        server=web,
        path="/srv/app/.env",
        content_sealed=seal(ENV_CONTENT, context=env_contexts.CONTENT),
        fingerprint=fingerprint(ENV_CONTENT, context=env_contexts.CONTENT),
        size=len(ENV_CONTENT),
        key_names=["SECRET_KEY"],
        source="pulled",
    )
    events = [
        audit.record("server.check", subject=str(web.pk), target="web-1"),
        audit.record(
            "backup.take",
            subject=str(shop.pk),
            target="shop",
            status=audit.FAILED,
            error_code="ssh_unreachable",
        ),
        audit.record("server.create", subject=str(retired.pk), target="web-1"),
    ]
    audit.seal_pending()
    return {
        "web": web,
        "shop": shop,
        "retired": retired,
        "plans": plans,
        "files": files,
        "version": version,
        "events": events,
        "sealed": {
            name: columns(OldServer._base_manager.get(pk=server.pk))
            for name, server in (("web", web), ("shop", shop), ("retired", retired))
        },
        "created_at": OldServer.objects.get(pk=web.pk).created_at,
    }


@pytest.mark.django_db(transaction=True)
def test_each_old_server_becomes_an_application_with_the_same_id(old_apps):
    old = fill(old_apps)

    migrate_to(latest())

    web = Application.all_objects.get(pk=old["web"].pk)
    shop = Application.all_objects.get(pk=old["shop"].pk)
    retired = Application.all_objects.get(pk=old["retired"].pk)
    assert Application.all_objects.count() == 3
    assert Server.all_objects.count() == 3
    assert len({web.server_id, shop.server_id, retired.server_id}) == 3
    assert {web.server_id, shop.server_id, retired.server_id}.isdisjoint(
        {old["web"].pk, old["shop"].pk, old["retired"].pk}
    )
    assert (web.kind, web.engine) == (Application.Kind.HOST, "")
    assert (web.project_dir, web.python_path, web.settings_module) == (
        "/srv/app",
        "/srv/app/.venv/bin/python",
        "shop.settings.prod",
    )
    assert (web.remote_backup_dir, web.file_roots, web.env_path) == (
        "/var/backups/web",
        ["/srv/app/media"],
        "/srv/app/.env",
    )
    assert (web.last_check_status, web.last_health) == ("ok", {"status": "ok"})
    assert web.created_by.username == "sara"
    assert (shop.kind, shop.engine) == (
        Application.Kind.COMPOSE,
        Application.Engine.DOCKER,
    )
    assert (shop.compose_service, shop.compose_files, shop.project_dir) == (
        "web",
        ["compose.yaml", "compose.prod.yaml"],
        "/srv/shop",
    )
    assert shop.timeout_in_container is True
    assert retired.deleted_at is not None
    assert not hasattr(web, "runtime")


@pytest.mark.django_db(transaction=True)
def test_each_application_gets_its_own_server_with_the_sealed_bytes_unchanged(
    old_apps,
):
    old = fill(old_apps)

    migrate_to(latest())

    for name in ("web", "shop", "retired"):
        application = Application.all_objects.get(pk=old[name].pk)
        server = Server.all_objects.get(pk=application.server_id)
        assert columns(server) == old["sealed"][name], name
        assert server.name == application.name
        assert server.deleted_at == application.deleted_at
        assert server.created_by_id == application.created_by_id
    web = Application.objects.get(pk=old["web"].pk)
    shop = Application.objects.get(pk=old["shop"].pk)
    assert web.server.created_at == old["created_at"]
    assert (web.server.host, web.server.port, web.server.username) == (
        "10.0.0.5",
        2222,
        "deploy",
    )
    assert (web.server.timeout_on_host, web.server.connection_state) == (
        True,
        "online",
    )
    assert (shop.server.connection_state, shop.server.last_connection_error) == (
        "offline",
        "ssh_unreachable",
    )
    assert (
        unseal_text(web.server.private_key_sealed, context=vault_contexts.PRIVATE_KEY)
        == PRIVATE_KEY
    )
    assert (
        unseal_text(
            web.server.key_passphrase_sealed, context=vault_contexts.KEY_PASSPHRASE
        )
        == KEY_PASSPHRASE
    )
    assert (
        unseal_text(shop.server.password_sealed, context=vault_contexts.PASSWORD)
        == SSH_PASSWORD
    )
    assert shop.server.private_key_sealed is None
    assert (
        unseal_text(
            web.backup_passphrase_sealed, context=vault_contexts.BACKUP_PASSPHRASE
        )
        == WEB_PASSPHRASE
    )
    assert (
        unseal_text(
            shop.backup_passphrase_sealed, context=vault_contexts.BACKUP_PASSPHRASE
        )
        == SHOP_PASSPHRASE
    )


@pytest.mark.django_db(transaction=True)
def test_plans_files_and_env_versions_follow_their_application(old_apps):
    old = fill(old_apps)

    migrate_to(latest())

    for name in ("web", "shop"):
        plan = BackupPlan.all_objects.get(pk=old["plans"][name].pk)
        assert plan.application_id == old[name].pk
    for file, owner in zip(old["files"], ("web", "shop", "retired")):
        moved = BackupFile.all_objects.get(pk=file.pk)
        assert moved.application_id == old[owner].pk
        assert moved.plan_id == file.plan_id
        assert moved.storage_path == file.storage_path
        assert moved.storage_path.startswith(f"{moved.application_id}/")
    version = EnvVersion.all_objects.get(pk=old["version"].pk)
    assert version.application_id == old["web"].pk
    assert unseal(version.content_sealed, context=env_contexts.CONTENT) == ENV_CONTENT


@pytest.mark.django_db(transaction=True)
def test_the_audit_trail_stays_intact_and_its_rows_name_the_applications(old_apps):
    old = fill(old_apps)
    before = audit.verify_chain()

    migrate_to(latest())

    after = audit.verify_chain()
    assert after.intact, after.reason
    assert (after.checked, after.head) == (before.checked, before.head)
    assert after.checked >= len(old["events"])
    for event, name in zip(old["events"], ("web", "shop", "retired")):
        entry = Logged(event)
        assert entry.application.pk == old[name].pk
        assert entry.server.pk == entry.application.server_id


@pytest.mark.django_db(transaction=True)
def test_going_back_to_0_7_restores_the_old_shape(old_apps):
    old = fill(old_apps)
    migrate_to(latest())
    web = Application.objects.get(pk=old["web"].pk)
    Server.objects.filter(pk=web.server_id).update(username="admin")

    apps = migrate_to([OLD])

    OldServer = apps.get_model("dbs_manager", "Server")
    assert set(OldServer._base_manager.values_list("pk", flat=True)) == {
        old["web"].pk,
        old["shop"].pk,
        old["retired"].pk,
    }
    web = OldServer._base_manager.get(pk=old["web"].pk)
    shop = OldServer._base_manager.get(pk=old["shop"].pk)
    retired = OldServer._base_manager.get(pk=old["retired"].pk)
    expected_web = {**old["sealed"]["web"], "username": "admin"}
    assert columns(web) == expected_web
    assert columns(shop) == old["sealed"]["shop"]
    assert (web.runtime, shop.runtime) == ("host", "compose")
    assert (shop.compose_service, shop.compose_files) == (
        "web",
        ["compose.yaml", "compose.prod.yaml"],
    )
    assert retired.deleted_at is not None
    assert (
        unseal_text(
            web.backup_passphrase_sealed, context=vault_contexts.BACKUP_PASSPHRASE
        )
        == WEB_PASSPHRASE
    )
    OldPlan = apps.get_model("dbs_manager", "BackupPlan")
    OldFile = apps.get_model("dbs_manager", "BackupFile")
    OldEnv = apps.get_model("dbs_manager", "EnvVersion")
    assert OldPlan._base_manager.get(pk=old["plans"]["shop"].pk).server_id == shop.pk
    for file, owner in zip(old["files"], ("web", "shop", "retired")):
        restored = OldFile._base_manager.get(pk=file.pk)
        assert (restored.server_id, restored.storage_path) == (
            old[owner].pk,
            file.storage_path,
        )
    assert OldEnv._base_manager.get(pk=old["version"].pk).server_id == web.pk
    tables = connection.introspection.table_names()
    assert "dbs_manager_application" not in tables
    assert "dbs_manager_server" in tables
    assert audit.verify_chain().intact


@pytest.mark.django_db
def test_the_shipped_migrations_match_the_models():
    out = io.StringIO()

    call_command("makemigrations", "dbs_manager", check=True, dry_run=True, stdout=out)

    assert "No changes detected" in out.getvalue()
