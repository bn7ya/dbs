from uuid import uuid4

import pytest

from dbs import audit
from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.backups.locks import TakeLock
from dbs.manager.backups.models import BackupFile, BackupPlan
from dbs.manager.backups.repositories import BackupFileRepository
from dbs.manager.backups.services import BackupService
from tests.manager.backups.support import BackupHost, server_tree
from tests.manager.servers.support import PASSWORD, connecting_to

CONNECT = "dbs.manager.servers.services.connection_service.connect"
RUNS_JOBS = pytest.mark.django_db(transaction=True)


@pytest.fixture
def host(monkeypatch, tmp_path):
    root = tmp_path / "server"
    server_tree(root)
    found = BackupHost(root=root)
    monkeypatch.setattr(CONNECT, connecting_to(found))
    return found


@pytest.fixture
def two_servers(make_server):
    return make_server(name="shop", host="10.0.0.5"), make_server(
        name="blog", host="10.0.0.6"
    )


@RUNS_JOBS
def test_take_all_backs_up_every_server_and_waits_for_each(
    terminal, admin, host, two_servers
):
    ran = terminal("backup", "take", "--all")

    assert ran.code == 0, ran.out + ran.err
    assert len(host.takes) == 2
    rows = dict(line.split()[:2] for line in ran.out.splitlines()[-2:])
    assert rows == {"blog": "ok", "shop": "ok"}
    assert BackupFile.objects.count() == 2
    takes = ActivityRepository().filtered(
        subject=None, action="backup.take", status=None
    )
    assert {entry.status for entry in takes} == {audit.SUCCEEDED}
    assert {entry.actor for entry in takes} == {admin}


@RUNS_JOBS
def test_take_reports_a_server_already_backing_up_and_fails(
    terminal, admin, host, two_servers
):
    shop, blog = two_servers
    TakeLock().acquire(blog.pk, uuid4())

    ran = terminal("backup", "take", "shop", "blog")

    assert ran.code == 1
    assert len(host.takes) == 1
    blog_row = next(line for line in ran.out.splitlines() if line.startswith("blog"))
    assert "failed" in blog_row


@pytest.mark.django_db
def test_take_needs_servers_or_all(terminal, admin, two_servers):
    assert "--all" in terminal("backup", "take").err
    assert "not both" in terminal("backup", "take", "shop", "--all").err


@RUNS_JOBS
def test_list_json_is_what_the_api_returns(terminal, api, admin, host, two_servers):
    shop, _ = two_servers
    terminal("backup", "take", "shop")

    listed = terminal("backup", "list", "--server", "shop", "--json").json()

    assert listed == api.get(f"/api/backups/?server={shop.pk}").json()["results"]


@RUNS_JOBS
def test_restore_rehearses_unless_real(terminal, admin, host, two_servers):
    terminal("backup", "take", "shop")
    backup = BackupFileRepository().all_including_deleted().get()

    rehearsed = terminal("backup", "restore", backup.pk, "--mode", "merge")
    refused = terminal(
        "backup",
        "restore",
        backup.pk,
        "--mode",
        "replace",
        "--real",
        "--confirm-name",
        "shop",
        "--password-stdin",
        stdin="wrong\n",
    )
    restored = terminal(
        "backup",
        "restore",
        backup.pk,
        "--mode",
        "replace",
        "--real",
        "--confirm-name",
        "shop",
        "--password-stdin",
        stdin=f"{PASSWORD}\n",
    )

    assert rehearsed.code == 0, rehearsed.err
    assert refused.code == 1
    assert restored.code == 0, restored.err
    assert [restore.dry_run for restore in host.restores] == [True, False]


@RUNS_JOBS
def test_restore_onto_another_server_needs_its_name(terminal, admin, host, two_servers):
    terminal("backup", "take", "shop")
    backup = BackupFileRepository().all_including_deleted().get()

    ran = terminal(
        "backup",
        "restore",
        backup.pk,
        "--mode",
        "merge",
        "--to",
        "blog",
        "--real",
        "--confirm-name",
        "shop",
        "--password-stdin",
        stdin=f"{PASSWORD}\n",
    )

    assert ran.code == 1 and "server name" in ran.err
    assert host.restores == []


@RUNS_JOBS
def test_download_upload_delete_and_undo(terminal, admin, host, two_servers, tmp_path):
    terminal("backup", "take", "shop")
    backup = BackupFileRepository().all_including_deleted().get()
    saved = tmp_path / "copy.dbs"

    assert terminal("backup", "download", backup.pk, "-o", saved).code == 0
    assert saved.read_bytes()[:3] == b"DBS"
    assert (
        "already exists" in terminal("backup", "download", backup.pk, "-o", saved).err
    )

    uploaded = terminal("backup", "upload", "blog", saved, "--json").json()
    assert uploaded["server_name"] == "blog" and uploaded["kind"] == "uploaded"

    assert terminal("backup", "delete", backup.pk).code == 0
    assert not BackupService(admin).list(two_servers[0].pk).exists()
    assert terminal("backup", "undo-delete", backup.pk).code == 0
    assert BackupService(admin).list(two_servers[0].pk).exists()


@RUNS_JOBS
def test_verify_waits_for_the_result(terminal, admin, host, two_servers):
    terminal("backup", "take", "shop")
    backup = BackupFileRepository().all_including_deleted().get()

    ran = terminal("backup", "verify", backup.pk)

    assert ran.code == 0, ran.err
    assert "Verified" in ran.out


@pytest.mark.django_db
def test_a_bad_backup_id_is_named(terminal, admin):
    assert "'nope' is not a backup id" in terminal("backup", "verify", "nope").err


@RUNS_JOBS
def test_plans_are_added_changed_run_and_removed(terminal, admin, host, two_servers):
    added = terminal(
        "plan",
        "add",
        "shop",
        "nightly",
        "--kind",
        "dbs",
        "--every",
        "1440",
        "--keep",
        "3",
        "--json",
    ).json()
    plan_id = added["id"]

    assert added["interval_minutes"] == 1440 and added["keep"] == 3
    assert terminal("plan", "edit", plan_id, "--manual", "--disable").code == 0
    plan = BackupPlan.objects.get(pk=plan_id)
    assert plan.interval_minutes is None and plan.enabled is False

    ran = terminal("plan", "run", plan_id)
    assert ran.code == 0, ran.err
    assert len(host.takes) == 1

    listed = terminal("plan", "list")
    assert "nightly" in listed.out and "manual" in listed.out
    assert terminal("plan", "remove", plan_id).code == 0
    assert "No plans yet." in terminal("plan", "list").out


@pytest.mark.django_db
def test_an_archive_plan_asks_for_the_account_password(terminal, admin, two_servers):
    refused = terminal(
        "plan", "add", "shop", "media", "--kind", "archive", "--path", "/srv/app/media"
    )
    added = terminal(
        "plan",
        "add",
        "shop",
        "media",
        "--kind",
        "archive",
        "--path",
        "/srv/app/media",
        "--password-stdin",
        stdin=f"{PASSWORD}\n",
    )

    assert refused.code == 1 and "--password-stdin" in refused.err
    assert added.code == 0, added.err
    assert BackupPlan.objects.get().paths == ["/srv/app/media"]


@RUNS_JOBS
def test_activity_shows_what_the_terminal_did_and_who(
    terminal, admin, host, two_servers
):
    terminal("backup", "take", "shop")

    listed = terminal("activity", "list", "--action", "backup.take", "--json").json()
    entry_id = listed[0]["id"]
    shown = terminal("activity", "show", entry_id, "--json").json()

    assert [entry["actor"] for entry in listed] == ["sara"]
    assert shown["status"] == "succeeded" and shown["server_name"] == "shop"
    assert (
        "Nothing has happened yet."
        in terminal("activity", "list", "--status", "running").out
    )
