from __future__ import annotations

import pytest

from dbs import audit
from dbs.manager.applications.repositories import ApplicationRepository
from dbs.models import AuditEvent
from tests.manager.relocation.conftest import SUDO_PASSWORD
from tests.manager.servers.support import PASSWORD
from tests.manager.terminal.conftest import terminal  # noqa: F401


def folder_arg(world):
    return f"shop={world['target_folder']}"


@pytest.mark.django_db(transaction=True)
def test_the_terminal_plans_a_move_and_says_what_it_carries(terminal, world):  # noqa: F811
    ran = terminal("server", "move", "old", "--to", "new", "--app", folder_arg(world), "--name", "shop=shop-new")

    assert ran.code == 0, ran.err
    assert "shop -> shop-new in" in ran.out
    assert "database sqlite (file): restore" in ran.out
    assert "note     venv_rebuilt" in ran.out
    assert not world["target_folder"].exists()


@pytest.mark.django_db(transaction=True)
def test_the_terminal_moves_for_real_with_both_passwords_on_stdin(terminal, world):  # noqa: F811
    ran = terminal(
        "server",
        "move",
        "old",
        "--to",
        "new",
        "--app",
        folder_arg(world),
        "--name",
        "shop=shop-new",
        "--real",
        "--confirm-name",
        "new",
        "--password-stdin",
        "--sudo-password-stdin",
        stdin=f"{PASSWORD}\n{SUDO_PASSWORD}\n",
    )

    assert ran.code == 0, ran.out + ran.err
    assert ApplicationRepository().name_in_use("shop-new")
    assert (world["target_folder"] / "manage.py").exists()
    assert SUDO_PASSWORD not in ran.out + ran.err


@pytest.mark.django_db(transaction=True)
def test_a_stopped_move_names_how_to_resume_it(terminal, world):  # noqa: F811
    ran = terminal(
        "server",
        "move",
        "old",
        "--to",
        "new",
        "--app",
        folder_arg(world),
        "--real",
        "--confirm-name",
        "new",
        "--password-stdin",
        "--sudo-password-stdin",
        stdin=f"{PASSWORD}\nnot-it\n",
    )

    job = AuditEvent.objects.get(action="relocation.move")
    assert ran.code == 1
    assert job.status == audit.FAILED
    assert f"--resume {job.pk}" in ran.out


@pytest.mark.django_db(transaction=True)
def test_an_application_on_another_server_cannot_be_named(terminal, world, admin):  # noqa: F811
    from tests.manager.factories import make_application

    make_application(admin, "blog", "10.0.0.9")

    ran = terminal("server", "move", "old", "--to", "new", "--app", "blog")

    assert ran.code == 1 and "does not run on old" in ran.err
