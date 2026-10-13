from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from dbs.manager import permissions
from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.backups.models import BackupFile
from dbs.manager.backups.repositories import BackupFileRepository
from dbs.manager.permissions import Capability, Role, RoleRequired, requires
from dbs.manager.servers.models import Server
from dbs.manager.servers.services import ServerService
from tests.manager.servers.support import (
    BACKUP_PASSPHRASE,
    PASSWORD,
    host_key_line,
    private_key_text,
)


@pytest.fixture
def server(db):
    return ServerService(None).create(
        name="web-1",
        host="10.0.0.5",
        username="deploy",
        auth_method=Server.AuthMethod.KEY,
        private_key=private_key_text(),
        host_key=host_key_line(),
        backup_passphrase=BACKUP_PASSPHRASE,
    )


@pytest.fixture
def backup(server):
    return BackupFileRepository().create(
        server=server,
        kind=BackupFile.Kind.DBS,
        name="nightly.dbs",
        size=11,
        sha256="0" * 64,
        storage_path=f"{server.pk}/nightly.dbs",
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
        Capability.BACKUPS_TAKE,
        Capability.BACKUPS_VERIFY,
        Capability.BACKUPS_DOWNLOAD,
        Capability.BACKUPS_REHEARSE,
        Capability.PLANS_RUN,
        Capability.ENV_PULL,
        Capability.FILES_DOWNLOAD,
        Capability.REDEPLOY_REHEARSE,
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
def test_a_viewer_reads_everything_and_changes_nothing(as_role, server, backup):
    viewer = as_role(Role.VIEWER)

    assert viewer.get("/api/servers/").status_code == 200
    assert viewer.get(f"/api/servers/{server.pk}/").status_code == 200
    assert viewer.get(f"/api/backups/?server={server.pk}").status_code == 200
    assert viewer.get("/api/activity/").status_code == 200
    assert viewer.get("/api/dashboard/").status_code == 200
    refused = refusal(viewer.post("/api/backups/take/", {"server": str(server.pk)}))
    assert refused["code"] == "role_required"
    assert refused["message"] == (
        "This needs the operator role or higher; your account is a viewer."
    )
    assert refusal(viewer.get(f"/api/backups/{backup.pk}/download/"))
    assert refusal(viewer.post(f"/api/servers/{server.pk}/check/"))


@pytest.mark.django_db
def test_an_operator_takes_and_rehearses_but_restores_nothing_for_real(
    as_role, server, backup
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
            "server_name": server.name,
        },
    )

    assert rehearsed.status_code == 202
    assert refusal(real)["message"] == (
        "This needs the admin role or higher; your account is an operator."
    )
    assert refusal(operator.delete(f"/api/backups/{backup.pk}/"))
    assert refusal(operator.delete(f"/api/servers/{server.pk}/"))
    assert refusal(operator.patch(f"/api/servers/{server.pk}/", {"name": "web-2"}))
    assert refusal(
        operator.post(f"/api/servers/{server.pk}/passphrase/", {"password": PASSWORD})
    )
    assert refusal(
        operator.post(
            "/api/backups/plans/",
            {"server": str(server.pk), "name": "nightly", "kind": "dbs"},
        )
    )
    assert refusal(operator.get("/api/accounts/"))


@pytest.mark.django_db
def test_an_operator_takes_backups(as_role, server):
    operator = as_role(Role.OPERATOR)

    assert (
        operator.post("/api/backups/take/", {"server": str(server.pk)}).status_code
        == 202
    )


@pytest.mark.django_db
def test_an_admin_restores_for_real_behind_the_password(as_role, server, backup):
    admin = as_role(Role.ADMIN)

    real = admin.post(
        f"/api/backups/{backup.pk}/restore/",
        {
            "mode": "merge",
            "rehearse": False,
            "account_password": PASSWORD,
            "server_name": server.name,
        },
    )
    unconfirmed = admin.post(
        f"/api/backups/{backup.pk}/restore/",
        {"mode": "merge", "rehearse": False, "server_name": server.name},
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
