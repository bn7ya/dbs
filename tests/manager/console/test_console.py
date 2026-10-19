from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from dbs import audit
from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.backups.models import BackupFile
from dbs.manager.backups.repositories import BackupFileRepository
from dbs.manager.conf import inline_jobs, jobs_inline
from dbs.manager.console.service import RUNNING
from dbs.manager.console.session import CappedText
from dbs.manager.permissions import Role
from dbs.models import AuditEvent
from tests.manager.backups.support import BackupHost, server_tree
from tests.manager.factories import make_application
from tests.manager.servers.support import BACKUP_PASSPHRASE, PASSWORD, connecting_to

CONSOLE = "/api/console/"
CONNECT = "dbs.manager.servers.services.connection_service.connect"


def ran(client, line, **body):
    response = client.post(CONSOLE, {"line": line, **body}, format="json")
    assert response.status_code == 200, response.content
    assert response["Cache-Control"] == "no-store"
    return response.json()


@pytest.fixture
def shop(admin):
    return make_application(
        admin,
        "shop",
        remote_backup_dir="/var/backups/dbs",
        backup_passphrase=BACKUP_PASSPHRASE,
    )


@pytest.fixture
def host(monkeypatch, tmp_path):
    root = tmp_path / "server"
    server_tree(root)
    found = BackupHost(root=root)
    monkeypatch.setattr(CONNECT, connecting_to(found))
    return found


@pytest.fixture
def viewer(db):
    user = UserRepository().create(username="vera", password=PASSWORD, role=Role.VIEWER)
    client = APIClient()
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_help_lists_what_the_console_offers_and_leaves_out_the_local_verbs(api):
    shown = ran(api, "help")
    backups = ran(api, "help backup")

    assert shown["exit_code"] == 0
    assert "server" in shown["output"] and "plan" in shown["output"]
    assert "mcp" not in shown["output"]
    assert "download" not in backups["output"] and "upload" not in backups["output"]
    assert "take" in backups["output"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "line",
    [
        "backup download 1",
        "files upload shop /tmp/x",
        "server add web --host h --user u",
        "env reveal 1",
        "mcp",
        "server list --as someone",
        "server list --password-stdin",
        "server list --data-dir /tmp",
        "app deploy-steps shop --set steps.json",
    ],
)
def test_what_reads_the_managers_own_disk_or_stdin_is_not_offered(api, line):
    result = ran(api, line)

    assert result["exit_code"] == 2
    assert "usage: django_dbs" in result["output"]


@pytest.mark.django_db
def test_a_command_runs_as_the_signed_in_account_and_is_recorded_without_its_words(
    api, admin, shop
):
    result = ran(api, "django_dbs app list --search sho")

    assert result["exit_code"] == 0, result
    assert "shop" in result["output"]
    [entry] = AuditEvent.objects.filter(action="console.command")
    assert entry.actor_id == admin.pk
    assert entry.data == {"verb": "app list", "exit_code": 0, "password_required": False}
    assert "sho" not in str(entry.data) and entry.target_name == "app list"


@pytest.mark.django_db
def test_a_viewer_reads_but_is_refused_what_needs_a_role(viewer, shop):
    listed = ran(viewer, "app list")
    refused = ran(viewer, "plan add shop nightly --kind dbs --every 1440")

    assert listed["exit_code"] == 0 and "shop" in listed["output"]
    assert refused["exit_code"] == 1
    assert refused["error_code"] == "role_required"
    assert "admin role" in refused["output"]


@pytest.mark.django_db
def test_a_command_that_needs_the_password_asks_for_it_and_runs_with_it(api, shop):
    file = BackupFileRepository().create(
        application=shop,
        kind=BackupFile.Kind.DBS,
        name="shop.dbs",
        size=1,
        sha256="0" * 64,
        storage_path=f"{shop.pk}/shop.dbs",
        validation=BackupFile.Validation.STRUCTURE_OK,
    )

    asked = ran(api, f"backup delete {file.pk}")
    deleted = ran(api, f"backup delete {file.pk}", password=PASSWORD)

    assert (asked["exit_code"], asked["password_required"]) == (1, True)
    assert deleted["exit_code"] == 0, deleted
    assert BackupFileRepository().find(file.pk) is None
    assert deleted["password_required"] is False


@pytest.mark.django_db
def test_a_job_is_started_and_returned_not_waited_for(
    api, shop, host, settings, monkeypatch, run_jobs
):
    settings.DBS_MANAGER_JOBS_INLINE = False
    submitted = []
    monkeypatch.setattr(
        "dbs.manager.runner.JobRunner.submit",
        lambda self, function, *args: submitted.append(args),
    )

    with run_jobs():
        result = ran(api, "backup take shop")

    assert result["exit_code"] == 0, result
    [job] = result["activities"]
    assert "started" in result["output"]
    assert AuditEvent.objects.get(pk=job).status == audit.QUEUED
    assert host.takes == []
    assert len(submitted) == 1


@pytest.mark.django_db
def test_a_single_job_reports_where_to_follow_it(api, shop, host, settings, monkeypatch):
    settings.DBS_MANAGER_JOBS_INLINE = False
    monkeypatch.setattr(
        "dbs.manager.runner.JobRunner.submit", lambda self, function, *args: None
    )
    plan = ran(api, "plan add shop nightly --kind dbs --every 1440 --json")
    plan_id = plan["output"].split('"id": "')[1].split('"')[0]

    result = ran(api, f"plan run {plan_id}")

    [job] = result["activities"]
    assert result["exit_code"] == 0
    assert f"follow it as activity {job}" in result["output"]


@pytest.mark.django_db
def test_a_bad_command_is_a_usage_error_never_an_exit(api):
    result = ran(api, "backup --bogus")
    unknown = ran(api, "nonsense")

    assert result["exit_code"] == 2 and "error:" in result["output"]
    assert unknown["exit_code"] == 2


@pytest.mark.django_db
def test_a_confirmation_needs_yes_in_the_console(api, shop):
    result = ran(api, "app remove shop")

    assert result["exit_code"] == 1
    assert "add --yes" in result["output"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "line, code",
    [("x" * 2001, "max_length"), ("plan add 'shop", "unbalanced_quotes")],
)
def test_a_line_too_long_or_unbalanced_is_refused(api, line, code):
    response = api.post(CONSOLE, {"line": line}, format="json")

    assert response.status_code == 400
    assert response.json()["error"]["fields"]["line"] == [code]


@pytest.mark.django_db
def test_an_account_runs_one_command_at_a_time(api, admin):
    with RUNNING.held(admin.pk):
        response = api.post(CONSOLE, {"line": "server list"}, format="json")

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "console_busy"
    assert ran(api, "server list")["exit_code"] == 0


@pytest.mark.django_db
def test_signed_out_no_command_runs(anonymous):
    response = anonymous.post(CONSOLE, {"line": "server list"}, format="json")

    assert response.status_code in (401, 403)
    assert not AuditEvent.objects.filter(action="console.command").exists()


def test_output_is_cut_at_its_limit():
    text = CappedText(limit=10)

    text.write("0123456789abc")
    text.write("more")

    assert text.getvalue().startswith("0123456789\n[the rest of the output was cut")
    assert text.getvalue().count("cut at") == 1


def test_jobs_run_inline_only_inside_the_switch(settings):
    settings.DBS_MANAGER_JOBS_INLINE = False

    with inline_jobs():
        inside = jobs_inline()

    assert inside is True and jobs_inline() is False


def test_the_console_offers_no_shell():
    from dbs.manager.console.parser import console_parser

    areas = console_parser()._subparsers._group_actions[0].choices

    assert not {"shell", "terminal", "exec", "mcp"} & set(areas)
