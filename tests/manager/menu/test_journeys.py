import pytest

from dbs import audit
from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.applications.models import Application
from dbs.manager.applications.repositories import ApplicationRepository
from dbs.manager.backups.models import BackupFile
from tests.manager.servers.support import PASSWORD, PROJECT_DIR, PYTHON
from tests.manager.support import logged

RUNS_JOBS = pytest.mark.django_db(transaction=True)
SERVERS = ("down", "enter")
APPLICATIONS = ("down", "down", "enter")
TO_THE_BUTTON = ["down"] * 30


def action(menu, label):
    labels = [row.cells[0] for row in menu.app.top.view.rows]
    menu.press("home", *["down"] * labels.index(label), "enter")


@pytest.mark.django_db
def test_an_application_is_added_from_its_servers_page(
    menu, admin, make_server, remote
):
    server = make_server()
    menu.press(*SERVERS, "enter")

    action(menu, "Add an application")
    menu.press("shop", "down", PROJECT_DIR, *TO_THE_BUTTON, "enter")

    assert "Done." in menu.screen and f"Added shop: {PROJECT_DIR}." in menu.screen
    assert "--server=web-1" in menu.screen and f"--folder={PROJECT_DIR}" in menu.screen
    application = ApplicationRepository().active().get(name="shop")
    assert application.server_id == server.pk
    assert (application.project_dir, application.python_path) == (PROJECT_DIR, PYTHON)
    assert application.last_check_status == Application.CheckStatus.OK
    assert [entry.actor for entry in logged("application.create")] == [admin]

    menu.press("enter")
    action(menu, "Applications")
    assert "shop" in menu.screen and "✓ Ready" in menu.line_with("shop")


@RUNS_JOBS
def test_a_backup_is_taken_verified_rehearsed_and_restored_from_one_applications_page(
    menu, admin, host, two_applications
):
    menu.press(*APPLICATIONS, "enter")
    action(menu, "Back up now")
    assert "Done." in menu.screen
    backup = BackupFile.objects.get()

    menu.press("enter")
    action(menu, "Backups")
    assert backup.name[:12] in menu.screen
    menu.press("enter")

    action(menu, "Verify")
    assert "Done." in menu.screen
    backup.refresh_from_db()
    assert backup.validation == BackupFile.Validation.VERIFIED

    menu.press("enter")
    action(menu, "Restore")
    menu.press("enter", "enter", *TO_THE_BUTTON, "enter")
    assert "Done." in menu.screen
    assert f"backup restore --mode=merge {backup.pk}" in menu.screen
    assert [restore.dry_run for restore in host.restores] == [True]

    menu.press("enter", "esc")
    assert "✓ Verified" in menu.line_with(backup.name[:12])


@RUNS_JOBS
def test_a_real_restore_asks_for_the_name_typed_out_and_the_password(
    menu, admin, host, two_applications
):
    menu.press(*APPLICATIONS, "enter")
    name = menu.app.top.title
    action(menu, "Back up now")
    menu.press("enter")
    action(menu, "Backups")
    menu.press("enter")
    action(menu, "Restore")

    menu.press("enter", "enter", "down", "down", "space", "down")
    assert "--real" in menu.line_with("Runs:")
    menu.press("enter", name, "enter", PASSWORD, "enter")

    assert menu.saw(f"Type the target application's name ({name}) to go ahead:")
    assert menu.saw(f"Password for {admin.get_username()}")
    assert "Done." in menu.screen
    assert [restore.dry_run for restore in host.restores] == [False]
    restores = ActivityRepository().filtered(action="backup.restore")
    assert [entry.status for entry in restores] == [audit.SUCCEEDED]


@RUNS_JOBS
def test_a_real_restore_stops_at_another_name(menu, host, two_applications):
    menu.press(*APPLICATIONS, "enter")
    action(menu, "Back up now")
    menu.press("enter")
    action(menu, "Backups")
    menu.press("enter")
    action(menu, "Restore")

    menu.press(
        "enter", "enter", "down", "down", "space", "down", "enter", "other", "enter"
    )

    assert "Stopped; nothing was changed." in menu.screen
    assert host.restores == []
