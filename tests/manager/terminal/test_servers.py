from datetime import timedelta

import pytest
from django.utils import timezone

from dbs.manager.servers.exceptions import SSHUnreachable
from dbs.manager.servers.gateways import parse_host_key
from dbs.manager.servers.models import Server
from dbs.manager.servers.repositories import ServerRepository
from dbs.manager.servers.services import ServerConnectionService
from dbs.manager.servers.services.server_service import DBS_VERSION
from tests.manager.servers.support import (
    BACKUP_DIR,
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
MANAGE_PY = (
    f'os.environ.setdefault("DJANGO_SETTINGS_MODULE", "{SETTINGS_MODULE}")\n'
).encode()


class ProjectRemote(FakeRemote):
    def read_small(self, path, limit):
        return MANAGE_PY if path == f"{PROJECT_DIR}/manage.py" else None


def ready_remote() -> FakeRemote:
    return ProjectRemote(
        answers={
            ("uname", "-sr"): Result(0, "Linux 6.1.0-18-amd64\n"),
            (PYTHON, "-c", DBS_VERSION): Result(0, "0.5.0\n"),
            (PYTHON, "manage.py", "dbs_backup", "--help"): Result(0, "usage\n"),
        },
        paths={f"{PROJECT_DIR}/manage.py", PYTHON, ENV_PATH, BACKUP_DIR},
    )


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
def test_add_with_a_password_pins_the_key_finds_the_project_and_checks_it(
    terminal, admin, offered, remote
):
    ran = terminal(
        "server",
        "add",
        "web-1",
        "--host",
        "10.0.0.5",
        "--port",
        "2222",
        "--user",
        "deploy",
        "--ssh-password-stdin",
        "--project-dir",
        PROJECT_DIR,
        "--yes",
        stdin=f"{SSH_PASSWORD}\n",
    )

    assert ran.code == 0, ran.err
    assert "SHA256:" in ran.out and "Found the project in /srv/app" in ran.out
    server = ServerRepository().active().get(name="web-1")
    assert server.host_key == offered
    assert server.python_path == PYTHON and server.env_path == ENV_PATH
    assert server.last_check_status == Server.CheckStatus.OK
    assert ServerConnectionService(admin).credentials(server).password == SSH_PASSWORD
    assert [entry.actor for entry in logged("server.create")] == [admin]


@pytest.mark.django_db
def test_add_asks_before_trusting_the_offered_key(
    terminal, admin, offered, remote, typing
):
    typing.append("n")

    ran = terminal(
        "server",
        "add",
        "web-1",
        "--host",
        "10.0.0.5",
        "--user",
        "deploy",
        "--key-file",
        "/nonexistent",
    )

    assert ran.code == 1 and "nothing was changed" in ran.err
    assert not ServerRepository().active().exists()


@pytest.mark.django_db
def test_add_from_a_script_needs_yes_to_trust_the_key(terminal, admin, offered, remote):
    ran = terminal(
        "server",
        "add",
        "web-1",
        "--host",
        "10.0.0.5",
        "--user",
        "deploy",
        "--generate-key",
    )

    assert ran.code == 1 and "--yes" in ran.err


@pytest.mark.django_db
def test_add_with_a_key_file_keeps_the_key(terminal, admin, offered, remote, tmp_path):
    key = tmp_path / "id_ed25519"
    key.write_text(private_key_text())

    ran = terminal(
        "server",
        "add",
        "web-1",
        "--host",
        "10.0.0.5",
        "--user",
        "deploy",
        "--key-file",
        key,
        "--host-key",
        host_key_line(),
        "--no-discover",
    )

    assert ran.code == 0, ran.err
    server = ServerRepository().active().get(name="web-1")
    assert (
        ServerConnectionService(admin).credentials(server).private_key
        == key.read_text()
    )


@pytest.mark.django_db
def test_add_with_a_new_key_prints_the_authorized_keys_line(terminal, admin, offered):
    ran = terminal(
        "server",
        "add",
        "web-1",
        "--host",
        "10.0.0.5",
        "--user",
        "deploy",
        "--generate-key",
        "--yes",
        "--json",
    )

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
def test_show_json_is_what_the_api_returns(terminal, api, admin, make_server):
    server = make_server()

    shown = terminal("server", "show", "web-1", "--json").json()

    assert shown == api.get(f"/api/servers/{server.pk}/").json()
    assert terminal("server", "show", str(server.pk), "--json").json() == shown


@pytest.mark.django_db
def test_editing_a_checked_servers_paths_asks_for_the_account_password(
    terminal, admin, make_server
):
    server = settled(make_server())

    refused = terminal("server", "edit", "web-1", "--python", "/usr/bin/python3")
    wrong = terminal(
        "server",
        "edit",
        "web-1",
        "--python",
        "/usr/bin/python3",
        "--password-stdin",
        stdin="not-it\n",
    )
    saved = terminal(
        "server",
        "edit",
        "web-1",
        "--python",
        "/usr/bin/python3",
        "--password-stdin",
        stdin=f"{PASSWORD}\n",
    )

    assert refused.code == 1 and "--password-stdin" in refused.err
    assert wrong.code == 1 and "password" in wrong.err.lower()
    assert saved.code == 0, saved.err
    server.refresh_from_db()
    assert server.python_path == "/usr/bin/python3"


@pytest.mark.django_db
def test_renaming_needs_no_password(terminal, admin, make_server):
    settled(make_server())

    assert terminal("server", "edit", "web-1", "--name", "web-2").code == 0
    assert ServerRepository().active().get().name == "web-2"


@pytest.mark.django_db
def test_remove_needs_the_name_typed_or_yes(terminal, admin, make_server, typing):
    make_server(name="web-1")
    make_server(name="web-2", host="10.0.0.6")
    typing.append("web")

    assert terminal("server", "remove", "web-1").code == 1
    typing.append("web-1")
    assert terminal("server", "remove", "web-1").code == 0
    assert terminal("server", "remove", "web-2", "--yes").code == 0
    assert not ServerRepository().active().exists()


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
    rows = {line.split()[0]: line for line in ran.out.splitlines()[1:]}
    assert " ok " in rows["web-1"] and "failed" in rows["web-2"]


@pytest.mark.django_db
def test_check_names_the_python_that_has_django_dbs(
    terminal, admin, make_server, monkeypatch
):
    make_server(python_path="python3")
    remote = ready_remote()
    monkeypatch.setattr(CONNECT, connecting_to(remote))

    ran = terminal("server", "check", "web-1")

    assert ran.code == 1
    assert f"--python {PYTHON}" in ran.out


@pytest.mark.django_db
def test_discover_save_writes_what_it_found(terminal, admin, make_server, remote):
    server = make_server(project_dir="", python_path="python3", env_path="")

    ran = terminal("server", "discover", "web-1", "--project", PROJECT_DIR, "--save")

    assert ran.code == 0, ran.err
    server.refresh_from_db()
    assert (server.project_dir, server.python_path) == (PROJECT_DIR, PYTHON)


@pytest.mark.django_db
def test_revealing_the_passphrase_needs_the_password(terminal, admin, make_server):
    make_server()

    assert (
        terminal("server", "passphrase", "web-1", "--password-stdin", stdin="x\n").code
        == 1
    )
    shown = terminal(
        "server", "passphrase", "web-1", "--password-stdin", stdin=f"{PASSWORD}\n"
    )
    assert shown.code == 0 and shown.out.strip() != ""


@pytest.mark.django_db
def test_import_profiles_adds_the_servers_of_a_client_config(
    terminal, admin, offered, tmp_path, monkeypatch
):
    key = tmp_path / "id_ed25519"
    key.write_text(private_key_text())
    config = tmp_path / "dbs-client.toml"
    config.write_text(
        f"""
[defaults]
username = "deploy"
key_filename = "{key}"
host_key = "{host_key_line()}"

[servers.shop]
host = "10.0.0.5"
project_dir = "/srv/shop"
python = "/srv/shop/.venv/bin/python"

[servers.blog]
host = "10.0.0.6"
"""
    )
    config.chmod(0o600)

    ran = terminal("server", "import-profiles", config)

    assert ran.code == 0, ran.out
    servers = {server.name: server for server in ServerRepository().active()}
    assert set(servers) == {"shop", "blog"}
    assert servers["shop"].python_path == "/srv/shop/.venv/bin/python"
    assert servers["shop"].project_dir == "/srv/shop"


@pytest.mark.django_db
def test_discover_save_on_a_checked_server_asks_for_the_password(
    terminal, admin, make_server, remote
):
    server = settled(make_server(project_dir="", python_path="python3", env_path=""))
    ServerRepository().update(server, last_check_status=Server.CheckStatus.OK)

    refused = terminal(
        "server", "discover", "web-1", "--project", PROJECT_DIR, "--save"
    )
    saved = terminal(
        "server",
        "discover",
        "web-1",
        "--project",
        PROJECT_DIR,
        "--save",
        "--password-stdin",
        stdin=f"{PASSWORD}\n",
    )

    assert refused.code == 1 and "--password-stdin" in refused.err
    assert saved.code == 0, saved.err
    server.refresh_from_db()
    assert server.python_path == PYTHON


@pytest.mark.django_db
def test_add_json_holds_the_server_and_its_check(terminal, admin, offered, remote):
    body = terminal(
        "server",
        "add",
        "web-1",
        "--host",
        "10.0.0.5",
        "--user",
        "deploy",
        "--ssh-password-stdin",
        "--project-dir",
        PROJECT_DIR,
        "--yes",
        "--json",
        stdin=f"{SSH_PASSWORD}\n",
    ).json()

    assert body["name"] == "web-1" and body["project_dir"] == PROJECT_DIR
    assert body["check"]["last_check_status"] == "ok"


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
