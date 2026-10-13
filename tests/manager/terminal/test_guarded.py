from __future__ import annotations

import stat

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.backups.models import BackupFile, BackupPlan
from dbs.manager.backups.services import BackupPlanService, BackupService
from dbs.manager.permissions import Role
from dbs.manager.servers.exceptions import HostKeyNotConfirmed, HostKeyRejected
from dbs.manager.servers.gateways import parse_host_key
from dbs.manager.servers.services import HostKeyConfirmationService
from tests.manager.backups.support import BackupHost
from tests.manager.servers.support import PASSWORD, connecting_to, host_key_line
from tests.manager.support import logged

FETCH_HOST_KEY = "dbs.manager.servers.services.server_service.fetch_host_key"
CONNECT = "dbs.manager.servers.services.connection_service.connect"
UPLOADED = b"-- PostgreSQL database dump\n"


@pytest.fixture
def plan(admin, make_server):
    server = make_server(name="shop")
    return BackupPlanService(admin).create(
        server=server.pk, name="nightly", kind="dbs", keep=3, keep_remote=2
    )


@pytest.mark.django_db
def test_keeping_fewer_asks_for_the_account_password(terminal, plan):
    refused = terminal("plan", "edit", plan.pk, "--keep", "2")
    wrong = terminal(
        "plan", "edit", plan.pk, "--keep-remote", "0", "--password-stdin", stdin="no\n"
    )
    saved = terminal(
        "plan",
        "edit",
        plan.pk,
        "--keep",
        "1",
        "--keep-remote",
        "0",
        "--password-stdin",
        stdin=f"{PASSWORD}\n",
    )

    assert refused.code == 1 and "--password-stdin" in refused.err
    assert wrong.code == 1
    assert saved.code == 0, saved.err
    stored = BackupPlan.objects.get(pk=plan.pk)
    assert (stored.keep, stored.keep_remote) == (1, 0)


@pytest.mark.django_db
def test_keeping_more_asks_nothing(terminal, plan):
    ran = terminal("plan", "edit", plan.pk, "--keep", "5", "--keep-remote", "5")

    assert ran.code == 0, ran.err
    stored = BackupPlan.objects.get(pk=plan.pk)
    assert (stored.keep, stored.keep_remote) == (5, 5)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "option", [("--keep", "0"), ("--keep", "6"), ("--keep-remote", "6")]
)
def test_the_terminal_keeps_one_to_five(terminal, capsys, plan, option):
    with pytest.raises(SystemExit) as stopped:
        terminal("plan", "add", "shop", "weekly", "--kind", "dbs", *option)

    assert stopped.value.code == 2
    assert "invalid choice" in capsys.readouterr().err
    assert BackupPlan.objects.count() == 1


@pytest.fixture
def held(monkeypatch, admin):
    key = parse_host_key(host_key_line())
    monkeypatch.setattr(FETCH_HOST_KEY, lambda host, port: key)
    return HostKeyConfirmationService(admin).request("10.0.0.5", 22)


@pytest.mark.django_db
def test_a_person_confirms_a_host_key_at_the_terminal(terminal, typing, admin, held):
    typing.append("y")

    ran = terminal("server", "confirm-host-key", held.id)

    assert ran.code == 0, ran.err
    assert held.fingerprint in ran.out and "10.0.0.5:22" in ran.out
    confirmations = HostKeyConfirmationService(admin)
    assert confirmations.approved(held.id, "10.0.0.5", 22) == held.line
    assert [entry.actor for entry in logged("server.host_key_confirm")] == [admin]


@pytest.mark.django_db
@pytest.mark.parametrize("answer", ["n", "", "yes please"])
def test_anything_but_yes_rejects_it(terminal, typing, admin, held, answer):
    typing.append(answer)

    ran = terminal("server", "confirm-host-key", held.id)

    assert ran.code == 1
    with pytest.raises(HostKeyRejected):
        HostKeyConfirmationService(admin).approved(held.id, "10.0.0.5", 22)


@pytest.mark.django_db
def test_a_script_cannot_confirm_a_host_key(terminal, admin, held):
    ran = terminal("server", "confirm-host-key", held.id, stdin="y\n")

    assert ran.code == 1 and "run it in a terminal" in ran.err
    with pytest.raises(HostKeyNotConfirmed):
        HostKeyConfirmationService(admin).approved(held.id, "10.0.0.5", 22)


@pytest.mark.django_db
@pytest.mark.parametrize("role", [Role.VIEWER, Role.OPERATOR])
def test_only_an_account_that_may_add_servers_is_asked_about_a_host_key(
    terminal, typing, admin, held, role
):
    UserRepository().create(username="vera", password=PASSWORD, role=role)

    ran = terminal("server", "confirm-host-key", held.id, "--as", "vera")

    assert ran.code == 1
    assert "admin role or higher" in ran.err
    assert held.fingerprint not in ran.out
    assert logged("server.host_key_confirm") == logged("server.host_key_reject") == []
    with pytest.raises(HostKeyNotConfirmed):
        HostKeyConfirmationService(admin).approved(held.id, "10.0.0.5", 22)


@pytest.mark.django_db
def test_an_unknown_confirmation_is_named(terminal, admin):
    ran = terminal("server", "confirm-host-key", "0badc0de")

    assert ran.code == 1 and "10 minutes" in ran.err


def mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.fixture
def uploaded(admin, make_server):
    server = make_server(name="shop")
    return BackupService(admin).upload(
        server.pk, SimpleUploadedFile("db.sql", UPLOADED)
    )


@pytest.mark.django_db(transaction=True)
def test_a_django_dbs_backup_is_saved_for_its_owner_alone(
    terminal, admin, make_server, monkeypatch, tmp_path
):
    monkeypatch.setattr(CONNECT, connecting_to(BackupHost(content=b"DBS")))
    make_server(name="shop")
    terminal("backup", "take", "shop")
    backup = BackupFile.objects.get()
    saved = tmp_path / "copy.dbs"

    ran = terminal("backup", "download", backup.pk, "-o", saved)

    assert ran.code == 0, ran.err
    assert saved.read_bytes() == b"DBS" and mode(saved) == 0o600


@pytest.mark.django_db
def test_saving_a_file_the_manager_sealed_asks_for_the_password(
    terminal, uploaded, tmp_path
):
    saved = tmp_path / "db.sql"

    refused = terminal("backup", "download", uploaded.pk, "-o", saved)
    left = saved.exists()
    ran = terminal(
        "backup",
        "download",
        uploaded.pk,
        "-o",
        saved,
        "--password-stdin",
        stdin=f"{PASSWORD}\n",
    )

    assert refused.code == 1 and "--password-stdin" in refused.err
    assert not left
    assert ran.code == 0, ran.err
    assert saved.read_bytes() == UPLOADED and mode(saved) == 0o600


@pytest.mark.django_db
def test_deleting_a_backup_asks_for_the_password(terminal, admin, uploaded):
    refused = terminal("backup", "delete", uploaded.pk)
    wrong = terminal(
        "backup", "delete", uploaded.pk, "--password-stdin", stdin="wrong\n"
    )

    assert refused.code == wrong.code == 1
    assert BackupFile.objects.filter(pk=uploaded.pk).exists()
    deleted = terminal(
        "backup", "delete", uploaded.pk, "--password-stdin", stdin=f"{PASSWORD}\n"
    )
    assert deleted.code == 0, deleted.err
    assert not BackupFile.objects.filter(pk=uploaded.pk).exists()


@pytest.mark.django_db
def test_saving_a_dotenv_file_asks_for_the_password(
    terminal, admin, make_server, local_host, tmp_path
):
    folder = tmp_path.resolve() / "srv"
    folder.mkdir()
    (folder / ".env").write_bytes(b"SECRET_KEY=x\n")
    make_server(name="shop", file_roots=[str(folder)])
    saved = tmp_path / "copy.env"

    refused = terminal("files", "download", "shop", f"{folder}/.env", "-o", saved)
    ran = terminal(
        "files",
        "download",
        "shop",
        f"{folder}/.env",
        "-o",
        saved,
        "--password-stdin",
        stdin=f"{PASSWORD}\n",
    )

    assert refused.code == 1 and "--password-stdin" in refused.err
    assert ran.code == 0, ran.err
    assert saved.read_bytes() == b"SECRET_KEY=x\n" and mode(saved) == 0o600
