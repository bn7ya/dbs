import json
import posixpath
from dataclasses import replace
from datetime import timedelta

import pytest
from django.utils import timezone

from dbs import audit
from dbs.manager.applications.repositories import ApplicationRepository
from dbs.manager.servers.exceptions import (
    ServerHasApplications,
    ServersDiffer,
    SSHUnreachable,
)
from dbs.manager.servers.gateways import EntryKind, RemoteEntry, parse_host_key
from dbs.manager.servers.models import Server
from dbs.manager.servers.repositories import ServerRepository
from dbs.manager.servers.services import ServerConnectionService
from tests.manager.servers.support import (
    BACKUP_DIR,
    DBS_VERSION,
    ENV_PATH,
    PASSWORD,
    PROJECT_DIR,
    PYTHON,
    SETTINGS_MODULE,
    SSH_PASSWORD,
    FakeRemote,
    Result,
    connecting_to,
    host_key_line,
    private_key_text,
    refusing_with,
)
from tests.manager.support import logged

CONNECT = "dbs.manager.servers.services.connection_service.connect"
FETCH_HOST_KEY = "dbs.manager.servers.services.server_service.fetch_host_key"
SETUP_OVER = timedelta(hours=2)
REMOTE_VERSION = "0.7.0"
PROJECT_FILES = ("manage.py", ".env")
MANAGE_PY = (
    f'os.environ.setdefault("DJANGO_SETTINGS_MODULE", "{SETTINGS_MODULE}")\n'
).encode()
DBS_CONNECTION = json.dumps({"dbs_connection": 2, "remote_backup_dir": BACKUP_DIR})
DOCKER_VERSION = ("docker", "version", "--format", "{{.Server.Version}}")
DOCKER_COMPOSE_VERSION = ("docker", "compose", "version", "--short")
PODMAN_VERSION = ("podman", "version", "--format", "{{.Version}}")


def listed(path: str, kind: str) -> RemoteEntry:
    return RemoteEntry(
        name=posixpath.basename(path),
        path=path,
        kind=kind,
        size=None,
        mtime=None,
        permissions=0o755,
        uid=0,
        gid=0,
    )


class ProjectRemote(FakeRemote):
    def read_small(self, path, limit):
        return MANAGE_PY if path == f"{PROJECT_DIR}/manage.py" else None

    def listdir(self, folder):
        if folder == posixpath.dirname(PROJECT_DIR):
            return [listed(PROJECT_DIR, EntryKind.FOLDER)]
        if folder == PROJECT_DIR:
            return [
                listed(posixpath.join(PROJECT_DIR, name), EntryKind.FILE)
                for name in PROJECT_FILES
            ]
        return []


def ready_remote() -> FakeRemote:
    return ProjectRemote(
        answers={
            ("uname", "-sr"): Result(0, "Linux 6.1.0-18-amd64\n"),
            (PYTHON, "-c", DBS_VERSION): Result(0, f"{REMOTE_VERSION}\n"),
            (PYTHON, "manage.py", "dbs_backup", "--help"): Result(0, "usage\n"),
            (PYTHON, "manage.py", "dbs", "connection", "--json"): Result(
                0, DBS_CONNECTION
            ),
        },
        paths={f"{PROJECT_DIR}/manage.py", PYTHON, ENV_PATH, BACKUP_DIR},
    )


def open_to_others(remote: FakeRemote, folder: str = PROJECT_DIR) -> FakeRemote:
    closed = remote.lstat

    def lstat(path):
        found = closed(path)
        return replace(found, permissions=0o777) if path == folder else found

    remote.lstat = lstat
    return remote


@pytest.fixture
def offered(monkeypatch):
    line = host_key_line()
    monkeypatch.setattr(FETCH_HOST_KEY, lambda host, port: parse_host_key(line))
    return line


@pytest.fixture
def remote(monkeypatch):
    found = ready_remote()
    monkeypatch.setattr(CONNECT, connecting_to(found))
    return found


def settled(server):
    return ServerRepository().update(server, created_at=timezone.now() - SETUP_OVER)


def adding(terminal, *options, stdin=""):
    return terminal(
        "server",
        "add",
        "web-1",
        "--host",
        "10.0.0.5",
        "--user",
        "deploy",
        *options,
        stdin=stdin,
    )


@pytest.mark.django_db
def test_list_says_how_to_add_the_first_server(terminal, admin):
    ran = terminal("server", "list")

    assert ran.code == 0
    assert "django_dbs server add" in ran.out


@pytest.mark.django_db
def test_without_an_account_it_points_to_createuser(terminal):
    ran = terminal("server", "list")

    assert ran.code == 1
    assert "django_dbs createuser" in ran.err


@pytest.mark.django_db
def test_with_several_accounts_it_asks_which_one(terminal, admin, django_user_model):
    django_user_model.objects.create_user(username="omar", password=PASSWORD)

    assert "--as NAME (omar, sara)" in terminal("server", "list").err
    assert terminal("server", "list", "--as", "omar").code == 0
    assert "no account named 'nadia'" in terminal("server", "list", "--as", "nadia").err


@pytest.mark.django_db
def test_add_with_a_password_pins_the_key_checks_it_and_says_how_to_add_the_application(
    terminal, admin, offered, remote
):
    ran = adding(
        terminal,
        "--port",
        "2222",
        "--ssh-password-stdin",
        "--yes",
        stdin=f"{SSH_PASSWORD}\n",
    )

    assert ran.code == 0, ran.err
    assert "SHA256:" in ran.out and "Added web-1." in ran.out
    assert "django_dbs app add NAME --server web-1 --folder FOLDER" in ran.out
    server = ServerRepository().active().get(name="web-1")
    assert server.host_key == offered and server.port == 2222
    assert server.last_check_status == Server.CheckStatus.OK
    assert ServerConnectionService(admin).credentials(server).password == SSH_PASSWORD
    assert [entry.actor for entry in logged("server.create")] == [admin]


@pytest.mark.django_db
def test_adding_a_server_looks_for_no_application(terminal, admin, offered, remote):
    ran = adding(terminal, "--ssh-password-stdin", "--yes", stdin=f"{SSH_PASSWORD}\n")

    assert ran.code == 0, ran.err
    assert not ApplicationRepository().active().exists()
    assert logged("application.discover") == []
    assert not [run for run in remote.runs if PYTHON in run["argv"]]
    assert [run["argv"][0] for run in remote.runs] == [
        "uname",
        "docker",
        "podman",
        "timeout",
    ]


@pytest.mark.parametrize(
    "option", [("--project-dir", PROJECT_DIR), ("--no-discover",), ("--python", PYTHON)]
)
def test_add_takes_no_application_settings(terminal, capsys, option):
    with pytest.raises(SystemExit) as stopped:
        adding(terminal, "--generate-key", "--yes", *option)

    assert stopped.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


@pytest.mark.django_db
def test_add_asks_before_trusting_the_offered_key(
    terminal, admin, offered, remote, typing
):
    typing.append("n")

    ran = adding(terminal, "--key-file", "/nonexistent")

    assert ran.code == 1 and "nothing was changed" in ran.err
    assert not ServerRepository().active().exists()


@pytest.mark.django_db
def test_add_from_a_script_needs_yes_to_trust_the_key(terminal, admin, offered, remote):
    ran = adding(terminal, "--generate-key")

    assert ran.code == 1 and "--yes" in ran.err


@pytest.mark.django_db
def test_add_with_a_key_file_keeps_the_key(terminal, admin, offered, remote, tmp_path):
    key = tmp_path / "id_ed25519"
    key.write_text(private_key_text())

    ran = adding(terminal, "--key-file", key, "--host-key", host_key_line())

    assert ran.code == 0, ran.err
    server = ServerRepository().active().get(name="web-1")
    assert (
        ServerConnectionService(admin).credentials(server).private_key
        == key.read_text()
    )


@pytest.mark.django_db
def test_add_with_a_new_key_prints_the_authorized_keys_line(terminal, admin, offered):
    ran = adding(terminal, "--generate-key", "--yes", "--json")

    body = ran.json()
    assert body["public_key"].startswith("ssh-ed25519 ")
    assert body["authorized_keys_hint"].endswith("~deploy/.ssh/authorized_keys")


@pytest.mark.django_db
def test_add_reports_the_same_validation_as_the_api(
    terminal, api, admin, offered, make_server
):
    make_server(name="web-1")

    ran = terminal(
        "server",
        "add",
        "web-1",
        "--host",
        "10.0.0.6",
        "--user",
        "deploy",
        "--generate-key",
        "--host-key",
        host_key_line(),
    )
    answer = api.post(
        "/api/servers/",
        {
            "name": "web-1",
            "host": "10.0.0.6",
            "username": "deploy",
            "generate_key": True,
            "host_key": host_key_line(),
        },
        format="json",
    )

    error = answer.json()["error"]
    assert ran.code == 1 and answer.status_code == 400
    assert error["fields"] == {"name": ["name_taken"]}
    assert ran.err.strip() == f"django_dbs: name: {error['message']}"


@pytest.mark.django_db
def test_add_json_holds_the_server_and_its_check(terminal, admin, offered, remote):
    body = adding(
        terminal,
        "--ssh-password-stdin",
        "--yes",
        "--json",
        stdin=f"{SSH_PASSWORD}\n",
    ).json()

    assert body["name"] == "web-1" and "project_dir" not in body
    assert body["check"]["last_check_status"] == "ok"
    assert set(body["check"]["engines"]) == {"docker", "podman"}
    assert SSH_PASSWORD not in json.dumps(body)


@pytest.mark.django_db
def test_show_json_is_what_the_api_returns(terminal, api, admin, make_server):
    server = make_server()

    shown = terminal("server", "show", "web-1", "--json").json()

    assert shown == api.get(f"/api/servers/{server.pk}/").json()
    assert terminal("server", "show", str(server.pk), "--json").json() == shown


@pytest.mark.django_db
def test_editing_a_settled_servers_address_asks_for_the_account_password(
    terminal, admin, make_server
):
    server = settled(make_server())

    refused = terminal("server", "edit", "web-1", "--host", "10.0.0.9")
    wrong = terminal(
        "server",
        "edit",
        "web-1",
        "--host",
        "10.0.0.9",
        "--password-stdin",
        stdin="not-it\n",
    )
    saved = terminal(
        "server",
        "edit",
        "web-1",
        "--host",
        "10.0.0.9",
        "--password-stdin",
        stdin=f"{PASSWORD}\n",
    )

    assert refused.code == 1 and "--password-stdin" in refused.err
    assert wrong.code == 1 and "password" in wrong.err.lower()
    assert saved.code == 0, saved.err
    server.refresh_from_db()
    assert server.host == "10.0.0.9"


@pytest.mark.django_db
def test_renaming_a_server_needs_no_password(terminal, admin, make_server):
    settled(make_server())

    assert terminal("server", "edit", "web-1", "--name", "web-2").code == 0
    assert ServerRepository().active().get().name == "web-2"


@pytest.mark.django_db
def test_editing_without_a_change_says_so(terminal, admin, make_server):
    make_server()

    ran = terminal("server", "edit", "web-1")

    assert ran.code == 1 and "nothing to change" in ran.err


@pytest.mark.django_db
def test_remove_needs_the_name_typed_or_yes_and_the_password(
    terminal, admin, make_server, typing
):
    make_server(name="web-1")
    make_server(name="web-2", host="10.0.0.6")
    typing.append("web")

    assert terminal("server", "remove", "web-1").code == 1
    typing.extend(["web-1", PASSWORD])
    assert terminal("server", "remove", "web-1").code == 0
    no_password = terminal(
        "server", "remove", "web-2", "--yes", "--password-stdin", stdin="\n"
    )
    assert no_password.code == 1 and ServerRepository().active().exists()
    removed = terminal(
        "server", "remove", "web-2", "--yes", "--password-stdin", stdin=f"{PASSWORD}\n"
    )
    assert removed.code == 0, removed.err
    assert not ServerRepository().active().exists()


@pytest.mark.django_db
def test_a_server_that_runs_an_application_is_not_removed(
    terminal, admin, make_application
):
    make_application(name="shop")

    ran = terminal(
        "server", "remove", "shop", "--yes", "--password-stdin", stdin=f"{PASSWORD}\n"
    )

    assert ran.code == 1
    assert str(ServerHasApplications.default_detail) in ran.err
    assert ServerRepository().active().filter(name="shop").exists()
    assert ApplicationRepository().active().filter(name="shop").exists()


@pytest.mark.django_db
def test_check_all_reports_every_server_and_fails_if_one_does(
    terminal, admin, make_server, monkeypatch
):
    make_server(name="web-1", host="10.0.0.5")
    make_server(name="web-2", host="10.0.0.6")
    healthy = connecting_to(ready_remote())
    broken = refusing_with(SSHUnreachable())
    monkeypatch.setattr(
        CONNECT,
        lambda credentials: (broken if credentials.host == "10.0.0.6" else healthy)(
            credentials
        ),
    )

    ran = terminal("server", "check", "--all")

    assert ran.code == 1
    assert ran.out.splitlines()[0].split() == [
        "SERVER",
        "CONNECTION",
        "STATUS",
        "ENGINES",
        "PROBLEM",
    ]
    rows = {line.split()[0]: line for line in ran.out.splitlines()[1:]}
    assert " online " in rows["web-1"] and " ok " in rows["web-1"]
    assert "offline (ssh_unreachable)" in rows["web-2"] and "failed" in rows["web-2"]

    listed_servers = terminal("server", "list").out.splitlines()
    assert listed_servers[0].split()[:6] == [
        "NAME",
        "HOST",
        "CONNECTION",
        "ENGINES",
        "APPLICATIONS",
        "STATUS",
    ]
    assert "online" in listed_servers[1]
    assert "offline (ssh_unreachable)" in listed_servers[2]


@pytest.mark.django_db
def test_check_names_the_container_engines_a_server_can_use(
    terminal, admin, make_server, monkeypatch
):
    server = make_server()
    remote = ready_remote()
    remote.answers[DOCKER_VERSION] = Result(0, "27.1.1\n")
    remote.answers[DOCKER_COMPOSE_VERSION] = Result(0, "2.29.1\n")
    remote.answers[PODMAN_VERSION] = Result(
        125, "", "Error: permission denied while reading the podman socket\n"
    )
    monkeypatch.setattr(CONNECT, connecting_to(remote))

    ran = terminal("server", "check", "web-1")

    assert ran.code == 0, ran.out + ran.err
    [row] = ran.out.splitlines()[1:]
    assert "docker 27.1.1" in row and "podman" not in row
    server.refresh_from_db()
    assert server.engines["docker"] == {
        "installed": True,
        "usable": True,
        "version": "27.1.1",
        "compose": "2.29.1",
        "error": "",
    }
    assert server.engines["podman"]["installed"] is True
    assert server.engines["podman"]["usable"] is False
    assert server.engines["podman"]["error"] == "engine_permission_denied"
    assert "docker 27.1.1" in terminal("server", "list").out


@pytest.mark.django_db
def test_check_needs_servers_or_all(terminal, admin, make_server):
    make_server()

    assert "choose all of them" in terminal("server", "check").err
    assert "not both" in terminal("server", "check", "web-1", "--all").err


@pytest.fixture
def same_machine(make_server):
    line = host_key_line()
    kept = make_server(name="web-1", host="10.0.0.5", host_key=line)
    joined = make_server(name="web-1-copy", host="10.0.0.5", host_key=line)
    return kept, joined


@pytest.mark.django_db
def test_merging_a_server_moves_its_applications_and_needs_the_password(
    terminal, admin, same_machine, make_application
):
    kept, joined = same_machine
    shop = make_application(name="shop", server=joined)

    refused = terminal("server", "merge", "web-1-copy", "--into", "web-1")
    wrong = terminal(
        "server",
        "merge",
        "web-1-copy",
        "--into",
        "web-1",
        "--password-stdin",
        stdin="not-it\n",
    )
    shop.refresh_from_db()
    left_alone = shop.server_id == joined.pk and ServerRepository().active().count()
    merged = terminal(
        "server",
        "merge",
        "web-1-copy",
        "--into",
        "web-1",
        "--password-stdin",
        stdin=f"{PASSWORD}\n",
    )

    assert refused.code == 1 and "--password-stdin" in refused.err
    assert wrong.code == 1
    assert left_alone == 2
    assert merged.code == 0, merged.err
    assert "Joined web-1-copy into web-1." in merged.out
    shop.refresh_from_db()
    assert shop.server_id == kept.pk
    assert list(ServerRepository().active()) == [kept]
    joined_entry, refused_entry = logged("server.merge")
    assert (joined_entry.status, refused_entry.status) == (
        audit.SUCCEEDED,
        audit.FAILED,
    )
    assert joined_entry.actor == admin and joined_entry.data["merged"] == "web-1-copy"


@pytest.mark.django_db
def test_only_the_same_machine_can_be_merged(
    terminal, admin, make_server, make_application
):
    make_server(name="web-1", host="10.0.0.5")
    other = make_server(name="web-2", host="10.0.0.6")
    blog = make_application(name="blog", server=other)

    ran = terminal(
        "server",
        "merge",
        "web-2",
        "--into",
        "web-1",
        "--password-stdin",
        stdin=f"{PASSWORD}\n",
    )

    assert ran.code == 1
    assert str(ServersDiffer.default_detail) in ran.err
    blog.refresh_from_db()
    assert blog.server_id == other.pk
    assert ServerRepository().active().count() == 2


def test_a_new_key_and_a_key_file_cannot_be_combined(terminal):
    with pytest.raises(SystemExit):
        terminal(
            "server",
            "add",
            "web-1",
            "--host",
            "h",
            "--user",
            "u",
            "--generate-key",
            "--key-file",
            "k",
        )
