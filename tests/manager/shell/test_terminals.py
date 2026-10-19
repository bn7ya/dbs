import base64
import logging
import shlex

import pytest
from rest_framework.test import APIClient

from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.permissions import Role
from dbs.manager.shell import sessions
from dbs.manager.shell.service import SHELLS, sweep_terminals
from dbs.models import AuditEvent
from tests.manager.shell.conftest import opened, output
from tests.manager.support import PASSWORD

SECRET_TYPED = "echo hunter2-secret-typed"


def decoded(response):
    return base64.b64decode(response.json()["data"])


@pytest.mark.django_db
def test_a_server_terminal_asks_for_a_pty_of_its_size_and_runs_a_login_shell(
    api, ssh, server
):
    response = opened(api, mode="server", server=str(server.pk), cols=132, rows=40)

    assert response.status_code == 201
    body = response.json()
    assert body["mode"] == "server" and body["server"] == str(server.pk)
    assert body["cols"] == 132 and body["rows"] == 40 and body["closed"] is False
    assert len(body["id"]) >= 32
    assert ssh.opened == [{"command": None, "cols": 132, "rows": 40}]
    assert ssh.channels[0].shell is True
    entry = AuditEvent.objects.get(action="shell.session")
    assert entry.status == "running" and entry.subject == str(server.pk)
    assert entry.data == {
        "mode": "server",
        "server": str(server.pk),
        "application": "",
        "container": "",
        "cols": 132,
        "rows": 40,
    }


@pytest.mark.django_db
def test_a_host_application_terminal_opens_a_login_shell_in_its_folder(
    api, ssh, host_application
):
    opened(api, mode="application", application=str(host_application.pk))

    command = ssh.opened[0]["command"]
    script = shlex.split(command)[-1]
    assert command.startswith("/bin/sh -c ")
    assert script.splitlines()[0] == "cd /srv/shop || exit 1"
    assert script.splitlines()[-1] == "exec sh -c " + shlex.quote(
        'exec "${SHELL:-/bin/sh}" -l'
    )


@pytest.mark.django_db
def test_a_compose_application_terminal_runs_a_shell_in_its_service(
    api, ssh, compose_application
):
    opened(api, mode="application", application=str(compose_application.pk))

    script = shlex.split(ssh.opened[0]["command"])[-1]
    lines = script.splitlines()
    assert lines[0] == "cd /srv/blog || exit 1"
    argv = shlex.split(lines[-1])[1:]
    assert argv[:8] == [
        "podman",
        "compose",
        "-f",
        "compose.prod.yaml",
        "exec",
        "-w",
        "/app",
        "web",
    ]
    assert argv[8:10] == ["sh", "-c"] and "exec bash -l" in argv[10]


@pytest.mark.django_db
def test_a_container_application_terminal_runs_docker_exec_with_a_tty(
    api, ssh, container_application
):
    opened(api, mode="application", application=str(container_application.pk))

    script = shlex.split(ssh.opened[0]["command"])[-1]
    argv = shlex.split(script.splitlines()[-1])[1:]
    assert argv[:4] == ["docker", "exec", "-it", "wiki-web"]
    assert argv[4:6] == ["sh", "-c"]


@pytest.mark.django_db
def test_output_arrives_from_the_cursor_and_typed_input_reaches_the_shell(
    api, ssh, server
):
    terminal = opened(api, mode="server", server=str(server.pk)).json()["id"]
    channel = ssh.channels[0]
    channel.emit(b"$ ")

    first = output(api, terminal, 0)
    sent = api.post(
        f"/api/terminals/{terminal}/input/", {"seq": 0, "data": "ls\r"}, format="json"
    )
    again = api.post(
        f"/api/terminals/{terminal}/input/", {"seq": 0, "data": "ls\r"}, format="json"
    )
    channel.emit(b"ls\r\nmanage.py\r\n$ ")
    second = output(api, terminal, first.json()["cursor"])

    assert first.status_code == 200 and decoded(first) == b"$ "
    assert first["Cache-Control"] == "no-store" and first["X-Accel-Buffering"] == "no"
    assert first.json()["cursor"] == 2 and first.json()["skipped"] is False
    assert sent.json() == {"accepted": True} and again.json() == {"accepted": False}
    assert bytes(channel.sent) == b"ls\r"
    assert decoded(second) == b"ls\r\nmanage.py\r\n$ "
    assert second.json()["cursor"] == 2 + len(b"ls\r\nmanage.py\r\n$ ")


@pytest.mark.django_db
def test_a_resize_reaches_the_pty_and_stays_within_bounds(api, ssh, server):
    terminal = opened(api, mode="server", server=str(server.pk)).json()["id"]

    resized = api.post(
        f"/api/terminals/{terminal}/resize/", {"cols": 100, "rows": 30}, format="json"
    )
    too_small = api.post(
        f"/api/terminals/{terminal}/resize/", {"cols": 5, "rows": 30}, format="json"
    )

    assert resized.status_code == 200 and resized.json()["cols"] == 100
    assert ssh.channels[0].sizes == [(100, 30)]
    assert too_small.status_code == 400


@pytest.mark.django_db
def test_a_terminal_that_exits_reports_its_status_and_records_no_keystroke(
    api, ssh, server, caplog
):
    caplog.set_level(logging.DEBUG)
    terminal = opened(api, mode="server", server=str(server.pk)).json()["id"]
    channel = ssh.channels[0]
    api.post(
        f"/api/terminals/{terminal}/input/",
        {"seq": 0, "data": SECRET_TYPED + "\r"},
        format="json",
    )
    channel.emit(b"hunter2-secret-typed\r\n")
    channel.exit(3)

    last = output(api, terminal, 0).json()
    gone = output(api, terminal, last["cursor"])

    assert last["closed"] is True and last["exit_status"] == 3
    assert last["reason"] == "exited"
    assert gone.status_code == 200
    assert (gone.json()["closed"], gone.json()["reason"], gone.json()["exit_status"]) == (
        True,
        "exited",
        3,
    )
    entry = AuditEvent.objects.get(action="shell.session")
    assert entry.status == "succeeded"
    assert entry.data["reason"] == "exited" and entry.data["exit_status"] == 3
    assert entry.data["bytes_in"] == len(SECRET_TYPED) + 1
    assert entry.data["bytes_out"] == len(b"hunter2-secret-typed\r\n")
    assert ssh.closed == 1
    for row in AuditEvent.objects.all():
        assert "hunter2" not in f"{row.data} {row.detail} {row.target_name}"
    assert "hunter2" not in caplog.text


@pytest.mark.django_db
def test_closing_a_terminal_ends_it_and_frees_its_connection(api, ssh, server):
    terminal = opened(api, mode="server", server=str(server.pk)).json()["id"]

    closed = api.delete(f"/api/terminals/{terminal}/")

    assert closed.status_code == 204
    assert ssh.channels[0].closed is True and ssh.closed == 1
    assert api.get("/api/terminals/").json() == {"results": []}
    told = output(api, terminal).json()
    assert (told["closed"], told["reason"]) == (True, "closed")
    entry = AuditEvent.objects.get(action="shell.session")
    assert entry.status == "succeeded" and entry.data["reason"] == "closed"


@pytest.mark.django_db
def test_every_terminal_asks_for_the_account_password(api, ssh, server):
    missing = api.post(
        "/api/terminals/", {"mode": "server", "server": str(server.pk)}, format="json"
    )
    wrong = api.post(
        "/api/terminals/",
        {"mode": "server", "server": str(server.pk), "password": "not-it"},
        format="json",
    )

    assert missing.status_code == 400
    assert missing.json()["error"]["fields"] == {"password": ["required"]}
    assert wrong.status_code == 400
    assert ssh.opened == []
    assert not AuditEvent.objects.filter(action="shell.session").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("role", [Role.OPERATOR, Role.VIEWER])
def test_only_admins_may_open_a_terminal(ssh, server, role):
    user = UserRepository().create(username="omar", password=PASSWORD, role=role)
    client = APIClient()
    client.force_login(user)

    response = opened(client, mode="server", server=str(server.pk))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "role_required"
    assert ssh.opened == []


@pytest.mark.django_db
def test_the_terminal_can_be_kept_for_the_master_or_switched_off(
    api, ssh, server, settings
):
    settings.DBS_MANAGER_TERMINAL = "master"
    for_master = opened(api, mode="server", server=str(server.pk))
    settings.DBS_MANAGER_TERMINAL = "off"
    switched_off = opened(api, mode="server", server=str(server.pk))

    assert for_master.status_code == 403
    assert for_master.json()["error"]["code"] == "role_required"
    assert switched_off.status_code == 403
    assert switched_off.json()["error"]["code"] == "terminal_off"
    assert ssh.opened == []


@pytest.mark.django_db
def test_a_service_without_an_account_never_opens_a_terminal(ssh, server):
    from dbs.manager.shell.exceptions import TerminalNeedsAccount
    from dbs.manager.shell.service import ShellService

    with pytest.raises(TerminalNeedsAccount):
        ShellService(None).open(mode="server", server=server.pk, password=PASSWORD)

    assert ssh.opened == []


@pytest.mark.django_db
def test_an_account_holds_two_terminals_and_the_manager_four(
    api, ssh, server, other_api
):
    mine = [opened(api, mode="server", server=str(server.pk)) for _ in range(3)]
    theirs = [opened(other_api, mode="server", server=str(server.pk)) for _ in range(2)]
    third = UserRepository().create(username="lina", password=PASSWORD)
    client = APIClient()
    client.force_login(third)
    fifth = opened(client, mode="server", server=str(server.pk))

    assert [response.status_code for response in mine] == [201, 201, 429]
    assert mine[2].json()["error"]["code"] == "too_many_terminals"
    assert [response.status_code for response in theirs] == [201, 201]
    assert fifth.status_code == 429


@pytest.mark.django_db
def test_another_account_can_neither_see_nor_type_into_my_terminal(
    api, ssh, server, other_api
):
    terminal = opened(api, mode="server", server=str(server.pk)).json()["id"]

    listed = other_api.get("/api/terminals/").json()
    read = output(other_api, terminal)
    typed = other_api.post(
        f"/api/terminals/{terminal}/input/", {"seq": 0, "data": "id\r"}, format="json"
    )
    closed = other_api.delete(f"/api/terminals/{terminal}/")

    assert listed == {"results": []}
    assert [read.status_code, typed.status_code, closed.status_code] == [404] * 3
    assert bytes(ssh.channels[0].sent) == b""
    assert ssh.channels[0].closed is False


@pytest.mark.django_db
def test_signing_out_closes_the_terminal_at_once(api, ssh, server, admin):
    terminal = opened(api, mode="server", server=str(server.pk)).json()["id"]

    assert api.post("/api/auth/logout/").status_code in (200, 204)

    assert ssh.channels[0].closed is True and ssh.closed == 1
    entry = AuditEvent.objects.get(action="shell.session")
    assert entry.status == "succeeded" and entry.data["reason"] == "signed_out"
    api.force_login(admin)
    assert output(api, terminal).status_code == 404


@pytest.mark.django_db
def test_signing_out_elsewhere_leaves_this_sessions_terminal_open(
    api, ssh, server, admin
):
    opened(api, mode="server", server=str(server.pk))
    elsewhere = APIClient()
    elsewhere.force_login(admin)

    elsewhere.post("/api/auth/logout/")

    assert ssh.channels[0].closed is False


@pytest.mark.django_db
def test_a_password_change_closes_the_terminal(api, ssh, server, admin):
    terminal = opened(api, mode="server", server=str(server.pk)).json()["id"]
    admin.set_password("another-long-password-for-sara")
    admin.save(update_fields=["password"])

    refused = output(api, terminal)
    swept = sweep_terminals()

    assert refused.status_code == 403
    assert swept == 1
    assert ssh.channels[0].closed is True
    entry = AuditEvent.objects.get(action="shell.session")
    assert entry.data["reason"] == "revoked"


@pytest.mark.django_db
def test_switching_the_terminal_off_closes_open_ones_on_the_next_sweep(
    api, ssh, server, settings
):
    opened(api, mode="server", server=str(server.pk))
    settings.DBS_MANAGER_TERMINAL = "off"

    assert sweep_terminals() == 1
    assert ssh.channels[0].closed is True


@pytest.mark.django_db
def test_a_role_change_closes_the_terminal(api, ssh, server, admin):
    from dbs.manager.accounts.models import Account

    terminal = opened(api, mode="server", server=str(server.pk)).json()["id"]
    Account.objects.filter(user=admin).update(role=Role.OPERATOR)

    response = api.post(
        f"/api/terminals/{terminal}/input/", {"seq": 0, "data": "id\r"}, format="json"
    )

    assert response.status_code == 410
    assert bytes(ssh.channels[0].sent) == b""


@pytest.mark.django_db
@pytest.mark.parametrize(
    "field, seconds, reason",
    [
        ("last_input_at", sessions.IDLE_SECONDS, "idle"),
        ("last_poll_at", sessions.UNPOLLED_SECONDS, "unpolled"),
        ("opened_at", sessions.LIFETIME_SECONDS, "lifetime"),
    ],
)
def test_a_terminal_left_alone_is_closed_by_the_sweep(
    api, ssh, server, field, seconds, reason
):
    opened(api, mode="server", server=str(server.pk))
    [session] = SHELLS.every()
    setattr(session, field, getattr(session, field) - seconds)

    assert sweep_terminals() == 1

    assert ssh.channels[0].closed is True and SHELLS.every() == []
    entry = AuditEvent.objects.get(action="shell.session")
    assert entry.data["reason"] == reason


@pytest.mark.django_db
def test_input_larger_than_64_kib_is_refused(api, ssh, server):
    terminal = opened(api, mode="server", server=str(server.pk)).json()["id"]

    response = api.post(
        f"/api/terminals/{terminal}/input/",
        {"seq": 0, "data": "é" * (40 * 1024)},
        format="json",
    )

    assert response.status_code == 400
    assert bytes(ssh.channels[0].sent) == b""


@pytest.mark.django_db
def test_how_a_terminal_ended_is_told_its_owner_for_a_minute_only(
    api, ssh, server, other_api, monkeypatch
):
    terminal = opened(api, mode="server", server=str(server.pk)).json()["id"]
    api.delete(f"/api/terminals/{terminal}/")
    now = SHELLS.clock()

    theirs = output(other_api, terminal)
    monkeypatch.setattr(SHELLS, "clock", lambda: now + sessions.REMEMBERED_SECONDS)
    later = output(api, terminal)

    assert theirs.status_code == 404
    assert later.status_code == 404


@pytest.mark.django_db
def test_a_terminal_says_the_last_keystrokes_it_took(api, ssh, server):
    terminal = opened(api, mode="server", server=str(server.pk)).json()
    api.post(
        f"/api/terminals/{terminal['id']}/input/", {"seq": 7, "data": "ls\r"}, format="json"
    )

    [listed] = api.get("/api/terminals/").json()["results"]

    assert terminal["last_seq"] == -1
    assert listed["last_seq"] == 7
