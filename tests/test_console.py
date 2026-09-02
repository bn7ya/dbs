"""The per-target SSH console in the admin."""

import pytest
from django.contrib.auth.models import User
from django.test import Client

from dbs.models import AuditEvent, BackupTarget

SETUP = "/admin/dbs/panel/setup/"

CONFIGURE = {
    "level": "relaxed",
    "expected_networks": "",
    "trusted_networks": "127.0.0.0/8",
    "notify_emails": "",
}


@pytest.fixture
def target(db):
    return BackupTarget.objects.create(
        name="offsite",
        host="backups.example.com",
        username="deploy",
        remote_dir="/var/backups/app",
        known_hosts="/home/deploy/.ssh/known_hosts",
    )


@pytest.fixture
def panel(db):
    user = User.objects.create_superuser("root", "root@example.com", "pw")
    client = Client()
    client.force_login(user)
    client.post(SETUP, CONFIGURE)
    return client


def console_url(target):
    return f"/admin/dbs/backuptarget/{target.pk}/console/"


@pytest.mark.django_db
def test_the_console_page_renders_with_the_shell_disabled(panel, target):
    response = panel.get(console_url(target))

    assert response.status_code == 200
    assert b"DBS_ADMIN_CONSOLE_SHELL" in response.content
    assert b"disabled" in response.content


@pytest.mark.django_db
def test_a_free_form_command_is_refused_by_default(panel, target):
    response = panel.post(console_url(target), {"command": "id"})

    assert response.status_code == 403
    assert "disabled" in response.json()["output"]
    assert AuditEvent.objects.filter(action="console.shell", succeeded=False).exists()


@pytest.mark.django_db
def test_an_unknown_action_is_refused(panel, target):
    response = panel.post(console_url(target), {"action": "rm-rf"})

    assert response.status_code == 400


@pytest.mark.django_db
def test_a_provisioning_action_runs_and_is_audited(panel, target, fake_ssh):
    response = panel.post(console_url(target), {"action": "ensure_dir"})

    body = response.json()
    assert body["ok"] is True
    assert "/var/backups/app" in body["output"]
    assert AuditEvent.objects.filter(action="console.ensure_dir", succeeded=True).exists()


@pytest.mark.django_db
def test_listing_remote_backups_goes_through_the_transport(panel, target, fake_ssh):
    fake_ssh.write_remote("/var/backups/app", "backup-20260101-000000Z.dbs", b"x")

    body = panel.post(console_url(target), {"action": "list"}).json()

    assert body["ok"] is True
    assert "backup-20260101-000000Z.dbs" in body["output"]


@pytest.mark.django_db
def test_a_connection_failure_is_reported_not_raised(panel, target):
    response = panel.post(console_url(target), {"action": "check"})

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert AuditEvent.objects.filter(action="console.check", succeeded=False).exists()


@pytest.mark.django_db
def test_the_shell_runs_once_the_setting_allows_it(panel, target, fake_ssh, settings):
    settings.DBS_ADMIN_CONSOLE_SHELL = True

    response = panel.post(console_url(target), {"command": "echo hello"})

    assert response.status_code == 200
    assert AuditEvent.objects.filter(action="console.shell").exists()
    detail = AuditEvent.objects.filter(action="console.shell").first().detail
    assert detail == "echo hello"


@pytest.mark.django_db
def test_the_console_needs_a_superuser(db, target):
    staff = User.objects.create_user("clerk", "c@example.com", "pw", is_staff=True)
    client = Client()
    client.force_login(staff)

    assert client.get(console_url(target)).status_code in (403, 404)
    assert client.post(console_url(target), {"action": "check"}).status_code in (403, 404)


@pytest.mark.django_db
def test_an_unknown_target_is_a_404(panel):
    assert panel.get("/admin/dbs/backuptarget/9999/console/").status_code == 404
