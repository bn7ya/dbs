from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from dbs.manager import permissions
from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.backups.models import BackupFile
from dbs.manager.backups.repositories import BackupFileRepository
from dbs.manager.permissions import Capability, Role, RoleRequired, requires
from tests.manager.factories import make_application
from tests.manager.servers.support import BACKUP_PASSPHRASE, PASSWORD


@pytest.fixture
def application(db):
    return make_application(None, backup_passphrase=BACKUP_PASSPHRASE)


@pytest.fixture
def server(application):
    return application.server


@pytest.fixture
def backup(application):
    return BackupFileRepository().create(
        application=application,
        kind=BackupFile.Kind.DBS,
        name="nightly.dbs",
        size=11,
        sha256="0" * 64,
        storage_path=f"{application.pk}/nightly.dbs",
        validation=BackupFile.Validation.STRUCTURE_OK,
    )


@pytest.fixture
def as_role(db):
    def make(role):
        user = UserRepository().create(username=role, password=PASSWORD, role=role)
        client = APIClient()
        client.force_login(user)
        return client

    return make


def refusal(response):
    assert response.status_code == 403, response.content
    return response.json()["error"]


def test_each_role_holds_every_capability_of_the_roles_below_it():
    viewer = set(permissions.capabilities(Role.VIEWER))
    operator = set(permissions.capabilities(Role.OPERATOR))
    admin = set(permissions.capabilities(Role.ADMIN))
    master = set(permissions.capabilities(Role.MASTER))

    assert viewer == set()
    assert viewer < operator < admin < master == set(permissions.MINIMUM_ROLE)
    assert master - admin == {Capability.ACCOUNTS_MANAGE}
    assert operator == {
        Capability.SERVERS_CHECK,
        Capability.APPLICATIONS_CHECK,
        Capability.BACKUPS_TAKE,
        Capability.BACKUPS_VERIFY,
        Capability.BACKUPS_DOWNLOAD,
        Capability.BACKUPS_REHEARSE,
        Capability.PLANS_RUN,
        Capability.ENV_PULL,
        Capability.FILES_DOWNLOAD,
        Capability.REDEPLOY_REHEARSE,
    }
    assert admin - operator == {
        Capability.SERVERS_MANAGE,
        Capability.APPLICATIONS_MANAGE,
        Capability.APPLICATIONS_PASSPHRASE,
        Capability.BACKUPS_UPLOAD,
        Capability.BACKUPS_DELETE,
        Capability.BACKUPS_RESTORE,
        Capability.PLANS_MANAGE,
        Capability.ENV_REVEAL,
        Capability.ENV_PUSH,
        Capability.FILES_CHANGE,
        Capability.REDEPLOY_RUN,
        Capability.SHELL_OPEN,
    }


def test_a_refusal_names_the_role_needed_and_the_role_held():
    assert str(RoleRequired(Role.ADMIN, Role.OPERATOR).detail) == (
        "This needs the admin role or higher; your account is an operator."
    )
    assert str(RoleRequired(Role.MASTER, Role.ADMIN).detail) == (
        "Only the master account can do this; your account is an admin."
    )


class Restores:
    def __init__(self, user):
        self.user = user

    @requires(Capability.BACKUPS_RESTORE)
    def restore(self, backup, *, rehearse, password=""):
        return "restored"


@pytest.mark.django_db
def test_a_rehearsal_needs_less_than_the_real_thing():
    operator = UserRepository().create(
        username="omar", password=PASSWORD, role=Role.OPERATOR
    )

    assert Restores(operator).restore(1, rehearse=True) == "restored"
    with pytest.raises(RoleRequired) as refused:
        Restores(operator).restore(1, rehearse=False)
    assert refused.value.role == Role.ADMIN
    assert Restores(None).restore(1, rehearse=False) == "restored"


@pytest.mark.django_db
def test_a_disabled_account_holds_no_role():
    user = UserRepository().create(username="omar", password=PASSWORD)
    UserRepository().deactivate(user)

    assert permissions.role_of(user) is None
    assert not permissions.can(user, Capability.BACKUPS_TAKE)


@pytest.mark.django_db
def test_an_account_made_outside_the_manager_is_a_viewer(django_user_model):
    user = django_user_model.objects.create_user(username="omar", password=PASSWORD)

    assert permissions.role_of(user) == Role.VIEWER


@pytest.mark.django_db
def test_a_viewer_reads_everything_and_changes_nothing(
    as_role, server, application, backup
):
    viewer = as_role(Role.VIEWER)

    assert viewer.get("/api/servers/").status_code == 200
    assert viewer.get(f"/api/servers/{server.pk}/").status_code == 200
    assert viewer.get(f"/api/applications/?server={server.pk}").status_code == 200
    assert viewer.get(f"/api/applications/{application.pk}/").status_code == 200
    assert viewer.get(f"/api/backups/?application={application.pk}").status_code == 200
    assert viewer.get("/api/activity/").status_code == 200
    assert viewer.get("/api/dashboard/").status_code == 200
    refused = refusal(
        viewer.post("/api/backups/take/", {"application": str(application.pk)})
    )
    assert refused["code"] == "role_required"
    assert refused["message"] == (
        "This needs the operator role or higher; your account is a viewer."
    )
    assert refusal(viewer.get(f"/api/backups/{backup.pk}/download/"))
    assert refusal(viewer.post(f"/api/servers/{server.pk}/check/"))
    assert refusal(viewer.post(f"/api/applications/{application.pk}/check/"))


@pytest.mark.django_db
def test_an_operator_takes_and_rehearses_but_restores_nothing_for_real(
    as_role, server, application, backup
):
    operator = as_role(Role.OPERATOR)
    restore = f"/api/backups/{backup.pk}/restore/"

    rehearsed = operator.post(restore, {"mode": "merge", "rehearse": True})
    real = operator.post(
        restore,
        {
            "mode": "merge",
            "rehearse": False,
            "account_password": PASSWORD,
            "application_name": application.name,
        },
    )

    assert rehearsed.status_code == 202
    assert refusal(real)["message"] == (
        "This needs the admin role or higher; your account is an operator."
    )
    assert refusal(operator.delete(f"/api/backups/{backup.pk}/"))
    assert refusal(operator.delete(f"/api/servers/{server.pk}/"))
    assert refusal(operator.patch(f"/api/servers/{server.pk}/", {"name": "web-2"}))
    assert refusal(operator.delete(f"/api/applications/{application.pk}/"))
    assert refusal(
        operator.patch(f"/api/applications/{application.pk}/", {"name": "web-2"})
    )
    assert refusal(
        operator.post(
            f"/api/applications/{application.pk}/passphrase/", {"password": PASSWORD}
        )
    )
    assert refusal(
        operator.post(f"/api/applications/{application.pk}/passphrase/capture/")
    )
    assert refusal(
        operator.post("/api/applications/discover/", {"server": str(server.pk)})
    )
    assert refusal(
        operator.post(
            "/api/applications/",
            {"server": str(server.pk), "name": "web-2"},
            format="json",
        )
    )
    assert refusal(
        operator.post(
            "/api/backups/plans/",
            {"application": str(application.pk), "name": "nightly", "kind": "dbs"},
        )
    )
    assert refusal(operator.get("/api/accounts/"))


@pytest.mark.django_db
def test_an_operator_rehearses_putting_a_server_back_but_never_does_it(as_role):
    revert = "/api/redeploy/999999/revert/"
    operator = as_role(Role.OPERATOR)

    real = operator.post(
        revert,
        {"rehearsal": False, "password": PASSWORD, "confirm_name": "web-2"},
        format="json",
    )
    rehearsed = operator.post(revert, {"rehearsal": True}, format="json")
    watched = as_role(Role.VIEWER).post(revert, {"rehearsal": True}, format="json")

    assert refusal(real)["message"] == (
        "This needs the admin role or higher; your account is an operator."
    )
    assert rehearsed.status_code == 404
    assert refusal(watched)["code"] == "role_required"


@pytest.mark.django_db
def test_an_operator_takes_backups(as_role, application):
    operator = as_role(Role.OPERATOR)

    assert (
        operator.post(
            "/api/backups/take/", {"application": str(application.pk)}
        ).status_code
        == 202
    )


@pytest.mark.django_db
def test_an_admin_restores_for_real_behind_the_password(as_role, application, backup):
    admin = as_role(Role.ADMIN)

    real = admin.post(
        f"/api/backups/{backup.pk}/restore/",
        {
            "mode": "merge",
            "rehearse": False,
            "account_password": PASSWORD,
            "application_name": application.name,
        },
    )
    unconfirmed = admin.post(
        f"/api/backups/{backup.pk}/restore/",
        {"mode": "merge", "rehearse": False, "application_name": application.name},
    )

    assert real.status_code == 202
    assert unconfirmed.status_code == 400
    assert "account_password" in unconfirmed.json()["error"]["fields"]
    assert refusal(admin.get("/api/accounts/"))["message"] == (
        "Only the master account can do this; your account is an admin."
    )


@pytest.mark.django_db
def test_the_identity_lists_what_the_role_may_do(as_role):
    operator = as_role(Role.OPERATOR)

    identity = operator.get("/api/auth/me/").json()

    assert identity["role"] == Role.OPERATOR
    assert identity["capabilities"] == permissions.capabilities(Role.OPERATOR)
    assert identity["two_factor"] is False
