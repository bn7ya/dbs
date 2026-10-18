from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from dbs import audit
from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.backups.locks import TakeLock
from dbs.manager.backups.models import BackupFile, BackupPlan
from dbs.manager.backups.repositories import BackupFileRepository
from dbs.manager.backups.services import BackupService
from dbs.manager.servers.exceptions import DbsTooOld
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
def two_applications(make_application):
    return make_application(name="shop", host="10.0.0.5"), make_application(
        name="blog", host="10.0.0.6"
    )


@RUNS_JOBS
def test_take_all_backs_up_every_application_and_waits_for_each(
    terminal, admin, host, two_applications
):
    ran = terminal("backup", "take", "--all")

    assert ran.code == 0, ran.out + ran.err
    assert len(host.takes) == 2
    rows = dict(line.split()[:2] for line in ran.out.splitlines()[-2:])
    assert rows == {"blog": "ok", "shop": "ok"}
    assert BackupFile.objects.count() == 2
    takes = ActivityRepository().filtered(action="backup.take")
    assert {entry.status for entry in takes} == {audit.SUCCEEDED}
    assert {entry.actor for entry in takes} == {admin}
    assert {entry.subject for entry in takes} == {
        str(application.pk) for application in two_applications
    }
    assert ran.out.splitlines()[-3].split()[:2] == ["APPLICATION", "RESULT"]


@RUNS_JOBS
def test_a_take_whose_connection_breaks_is_kept_on_the_server_not_failed(
    terminal, admin, monkeypatch, tmp_path, make_application
):
    monkeypatch.setattr(
        CONNECT, connecting_to(BackupHost(root=tmp_path / "server", breaks=True))
    )
    make_application(name="shop")

    ran = terminal("backup", "take", "shop")
    shown = terminal("backup", "take", "shop", "--json")

    assert ran.code == 0, ran.out + ran.err
    assert "kept on the server; collected at the next connection" in ran.out
    assert shown.json()[0]["kept_on_server"] is True
    [collected] = BackupFile.objects.all()
    assert collected.validation == BackupFile.Validation.VERIFIED


@RUNS_JOBS
def test_take_reports_an_application_already_backing_up_and_fails(
    terminal, admin, host, two_applications
):
    shop, blog = two_applications
    TakeLock().acquire(blog.pk, uuid4())

    ran = terminal("backup", "take", "shop", "blog")

    assert ran.code == 1
    assert len(host.takes) == 1
    blog_row = next(line for line in ran.out.splitlines() if line.startswith("blog"))
    assert "failed" in blog_row


@RUNS_JOBS
def test_an_application_whose_django_dbs_cannot_stream_names_the_version_it_needs(
    terminal, admin, monkeypatch, make_application
):
    too_old = DbsTooOld("0.7.0", output="error: unrecognized arguments: --stream")
    monkeypatch.setattr(CONNECT, connecting_to(BackupHost(failure=too_old)))
    make_application(name="shop")

    ran = terminal("backup", "take", "shop")

    assert ran.code == 1
    assert "Upgrade it to 0.7.0 or later." in ran.out
    assert "0.2.2" not in ran.out


@pytest.mark.django_db
def test_take_needs_applications_or_all(terminal, admin, two_applications):
    assert "choose all of them" in terminal("backup", "take").err
    assert "not both" in terminal("backup", "take", "shop", "--all").err


@RUNS_JOBS
def test_list_json_is_what_the_api_returns(
    terminal, api, admin, host, two_applications
):
    shop, _ = two_applications
    terminal("backup", "take", "shop", "blog")

    listed = terminal("backup", "list", "--app", "shop", "--json").json()
    every = terminal("backup", "list", "--json").json()

    assert listed == api.get(f"/api/backups/?application={shop.pk}").json()["results"]
    assert [row["application_name"] for row in listed] == ["shop"]
    assert every == api.get("/api/backups/").json()["results"]
    assert {row["application_name"] for row in every} == {"shop", "blog"}


@RUNS_JOBS
def test_restore_rehearses_unless_real(terminal, admin, host, two_applications):
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
def test_restore_onto_another_application_needs_its_name(
    terminal, admin, host, two_applications
):
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

    assert ran.code == 1 and "application name" in ran.err
    assert host.restores == []


@RUNS_JOBS
def test_download_upload_delete_and_undo(
    terminal, admin, host, two_applications, tmp_path
):
    terminal("backup", "take", "shop")
    backup = BackupFileRepository().all_including_deleted().get()
    saved = tmp_path / "copy.dbs"

    assert terminal("backup", "download", backup.pk, "-o", saved).code == 0
    assert saved.read_bytes()[:3] == b"DBS"
    assert (
        "already exists" in terminal("backup", "download", backup.pk, "-o", saved).err
    )

    uploaded = terminal("backup", "upload", "blog", saved, "--json").json()
    assert uploaded["application_name"] == "blog" and uploaded["kind"] == "uploaded"
    assert uploaded["application"] == str(two_applications[1].pk)

    assert terminal("backup", "delete", backup.pk).code == 1
    assert BackupService(admin).list(two_applications[0].pk).exists()
    deleted = terminal(
        "backup", "delete", backup.pk, "--password-stdin", stdin=f"{PASSWORD}\n"
    )
    assert deleted.code == 0, deleted.err
    assert not BackupService(admin).list(two_applications[0].pk).exists()
    assert terminal("backup", "undo-delete", backup.pk).code == 0
    assert BackupService(admin).list(two_applications[0].pk).exists()


@RUNS_JOBS
def test_verify_waits_for_the_result(terminal, admin, host, two_applications):
    terminal("backup", "take", "shop")
    backup = BackupFileRepository().all_including_deleted().get()

    ran = terminal("backup", "verify", backup.pk)

    assert ran.code == 0, ran.err
    assert "Verified" in ran.out


@pytest.mark.django_db
def test_a_bad_backup_id_is_named(terminal, admin):
    assert "'nope' is not a backup id" in terminal("backup", "verify", "nope").err


@RUNS_JOBS
def test_plans_are_added_changed_run_and_removed(
    terminal, admin, host, two_applications
):
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
    assert listed.out.splitlines()[0].split()[:2] == ["APPLICATION", "NAME"]
    assert listed.out.splitlines()[1].split()[:2] == ["shop", "nightly"]
    assert "nightly" not in terminal("plan", "list", "--app", "blog").out
    assert terminal("plan", "remove", plan_id).code == 0
    assert "No plans yet." in terminal("plan", "list").out


@pytest.mark.django_db
def test_an_archive_plan_asks_for_the_account_password(
    terminal, admin, two_applications
):
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
    terminal, admin, host, two_applications
):
    terminal("backup", "take", "shop")

    listed = terminal("activity", "list", "--action", "backup.take", "--json").json()
    entry_id = listed[0]["id"]
    shown = terminal("activity", "show", entry_id, "--json").json()

    assert [entry["actor"] for entry in listed] == ["sara"]
    assert shown["status"] == "succeeded"
    assert (shown["application_name"], shown["server_name"]) == ("shop", "shop")
    assert (
        "Nothing has happened yet."
        in terminal("activity", "list", "--status", "running").out
    )


@RUNS_JOBS
def test_activity_lists_a_server_with_its_applications_or_one_application(
    terminal, admin, host, two_applications
):
    terminal("backup", "take", "--all")

    by_application = terminal("activity", "list", "--app", "shop", "--json").json()
    by_server = terminal("activity", "list", "--server", "blog", "--json").json()
    table = terminal("activity", "list").out.splitlines()

    assert {row["application_name"] for row in by_application} == {"shop"}
    assert {"application.create", "backup.take"} <= {
        row["action"] for row in by_application
    }
    assert {row["server_name"] for row in by_server} == {"blog"}
    assert {"server.create", "application.create", "backup.take"} <= {
        row["action"] for row in by_server
    }
    assert table[0].split()[4:6] == ["SERVER", "APPLICATION"]


@pytest.mark.django_db
def test_a_plan_is_rescheduled_paused_and_resumed_from_the_terminal(
    terminal, admin, two_applications
):
    added = terminal(
        "plan",
        "add",
        "shop",
        "nightly",
        "--kind",
        "dbs",
        "--every",
        "1440",
        "--first-run",
        "2099-01-01T03:00+01:00",
        "--time-zone",
        "Europe/Berlin",
        "--json",
    )
    assert added.code == 1 and "anchor at" in added.err
    first = (timezone.now() + timedelta(days=2)).replace(microsecond=0)
    added = terminal(
        "plan",
        "add",
        "shop",
        "nightly",
        "--kind",
        "dbs",
        "--every",
        "1440",
        "--first-run",
        first.isoformat(),
        "--time-zone",
        "Europe/Berlin",
        "--json",
    ).json()
    plan_id = added["id"]
    assert added["time_zone"] == "Europe/Berlin"
    assert parse_datetime(added["next_run_at"]) == first

    later = first + timedelta(hours=5)
    moved = terminal("plan", "reschedule", plan_id, "--at", later.isoformat())
    assert moved.code == 0, moved.err
    assert BackupPlan.objects.get(pk=plan_id).next_run_at == later

    assert terminal("plan", "pause", plan_id).code == 0
    paused = BackupPlan.objects.get(pk=plan_id)
    assert (paused.enabled, paused.next_run_at) == (False, None)

    resumed = terminal("plan", "resume", plan_id)
    assert resumed.code == 0, resumed.err
    assert "runs next at" in resumed.out
    assert BackupPlan.objects.get(pk=plan_id).next_run_at == later


@pytest.mark.django_db
def test_a_manual_plan_cannot_be_paused_or_rescheduled(
    terminal, admin, two_applications
):
    plan_id = terminal(
        "plan", "add", "shop", "adhoc", "--kind", "dbs", "--manual", "--json"
    ).json()["id"]

    paused = terminal("plan", "pause", plan_id)
    moved = terminal("plan", "reschedule", plan_id, "--at", "2099-01-01T00:00Z")

    assert paused.code == 1 and moved.code == 1
    assert "runs only when asked" in paused.err
