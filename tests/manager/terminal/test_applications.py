from datetime import timedelta

import pytest
from django.utils import timezone

from dbs.manager.applications.models import Application
from dbs.manager.applications.repositories import ApplicationRepository
from dbs.manager.servers.exceptions import SSHUnreachable
from dbs.manager.servers.repositories import ServerRepository
from dbs.manager.servers.services import ServerConnectionService
from tests.manager.servers.support import (
    BACKUP_DIR,
    BACKUP_PASSPHRASE,
    ENV_PATH,
    PASSWORD,
    PROJECT_DIR,
    PYTHON,
    SETTINGS_MODULE,
    Result,
    connecting_to,
    refusing_with,
)
from tests.manager.support import logged
from tests.manager.terminal.test_servers import (
    REMOTE_VERSION,
    open_to_others,
    ready_remote,
)

CONNECT = "dbs.manager.servers.services.connection_service.connect"
SETUP_OVER = timedelta(hours=2)
CANDIDATE_COLUMNS = [
    "N",
    "RUNS",
    "PYTHON",
    "DJANGO-DBS",
    "SETTINGS",
    "BACKUPS",
    "PROBLEMS",
]
CHECK_COLUMNS = [
    "APPLICATION",
    "SERVER",
    "CONNECTION",
    "STATUS",
    "DJANGO-DBS",
    "PROBLEM",
]


@pytest.fixture
def remote(monkeypatch):
    found = ready_remote()
    monkeypatch.setattr(CONNECT, connecting_to(found))
    return found


@pytest.fixture
def server(make_server):
    return make_server()


def settled_server(server):
    return ServerRepository().update(server, created_at=timezone.now() - SETUP_OVER)


def settled(application):
    return ApplicationRepository().update(
        application,
        created_at=timezone.now() - SETUP_OVER,
        last_check_status=Application.CheckStatus.OK,
    )


def adding(terminal, *options, name="shop", stdin=""):
    return terminal(
        "app",
        "add",
        name,
        "--server",
        "web-1",
        "--folder",
        PROJECT_DIR,
        *options,
        stdin=stdin,
    )


@pytest.mark.django_db
def test_list_says_how_to_add_the_first_application(terminal, admin):
    ran = terminal("app", "list")

    assert ran.code == 0
    assert "django_dbs app add" in ran.out


@pytest.mark.django_db
def test_list_shows_where_each_application_runs_and_filters_by_server(
    terminal, admin, make_application
):
    make_application(name="shop", host="10.0.0.5")
    make_application(
        name="blog",
        host="10.0.0.6",
        kind="compose",
        engine="docker",
        compose_service="backend",
        project_dir="/srv/blog",
    )

    every = terminal("app", "list").out.splitlines()
    only_shop = terminal("app", "list", "--server", "shop").out.splitlines()

    assert every[0].split() == ["NAME", "SERVER", "RUNS", "STATUS", "CHECKED", "ID"]
    rows = {line.split()[0]: line for line in every[1:]}
    assert "docker compose backend" in rows["blog"]
    assert PROJECT_DIR in rows["shop"]
    assert [line.split()[0] for line in only_shop[1:]] == ["shop"]


@pytest.mark.django_db
def test_show_json_is_what_the_api_returns(terminal, api, admin, make_application):
    application = make_application()

    shown = terminal("app", "show", "web-1", "--json").json()

    assert shown == api.get(f"/api/applications/{application.pk}/").json()
    assert terminal("app", "show", str(application.pk), "--json").json() == shown
    assert BACKUP_PASSPHRASE not in terminal("app", "show", "web-1").out


@pytest.mark.django_db
def test_discover_without_a_folder_suggests_the_folders_that_look_like_projects(
    terminal, admin, server, remote
):
    ran = terminal("app", "discover", "web-1")

    assert ran.code == 0, ran.err
    lines = ran.out.splitlines()
    assert lines[0] == "Folders that look like projects:"
    assert f"  {PROJECT_DIR}" in lines[1:]
    assert not ApplicationRepository().active().exists()


@pytest.mark.django_db
def test_discover_prints_each_place_the_application_could_run(
    terminal, admin, server, remote
):
    ran = terminal("app", "discover", "web-1", "--folder", PROJECT_DIR)

    assert ran.code == 0, ran.err
    lines = ran.out.splitlines()
    assert lines[0] == f"Folder  {PROJECT_DIR}"
    assert lines[1].split() == CANDIDATE_COLUMNS
    assert lines[2].split() == [
        "1",
        PROJECT_DIR,
        PYTHON,
        REMOTE_VERSION,
        SETTINGS_MODULE,
        BACKUP_DIR,
        "-",
    ]
    assert not ApplicationRepository().active().exists()
    [entry] = logged("application.discover")
    assert entry.actor == admin and entry.subject == str(server.pk)


@pytest.mark.django_db
def test_discover_json_is_what_the_api_returns(terminal, api, admin, server, remote):
    shown = terminal("app", "discover", "web-1", "--folder", PROJECT_DIR, "--json")

    answer = api.post(
        "/api/applications/discover/",
        {"server": str(server.pk), "folder": PROJECT_DIR},
        format="json",
    )

    assert answer.status_code == 200
    assert shown.json() == answer.json()
    [candidate] = shown.json()["candidates"]
    assert (candidate["kind"], candidate["python_path"]) == ("host", PYTHON)
    assert candidate["env"] == [
        {"path": ENV_PATH, "location": "host", "source": "folder"}
    ]


@pytest.mark.django_db
def test_discover_in_a_folder_without_a_project_says_so(
    terminal, admin, server, remote
):
    ran = terminal("app", "discover", "web-1", "--folder", "/srv/empty")

    assert ran.code == 0, ran.err
    assert ran.out.splitlines()[-1] == "Found no Django project here."


@pytest.mark.django_db
def test_a_relative_folder_is_refused_before_anything_runs(
    terminal, admin, server, remote
):
    ran = terminal("app", "discover", "web-1", "--folder", "srv/app")

    assert ran.code != 0
    assert "absolute path" in ran.err
    assert remote.runs == []


@pytest.mark.django_db
def test_nothing_is_run_in_a_folder_others_can_write_to(
    terminal, admin, server, remote
):
    open_to_others(remote)

    found = terminal("app", "discover", "web-1", "--folder", PROJECT_DIR)
    added = adding(terminal)

    assert found.code == 0, found.err
    assert found.out.splitlines() == [
        f"Folder  {PROJECT_DIR}",
        "This folder or its parent can be written by others, so nothing in it was run.",
    ]
    assert added.code == 1
    assert added.err.strip() == (
        f"django_dbs: {PROJECT_DIR} or its parent can be written by others, so "
        "nothing in it was run."
    )
    assert remote.runs == []
    assert not ApplicationRepository().active().exists()


@pytest.mark.django_db
def test_discover_on_a_settled_server_asks_for_the_account_password(
    terminal, admin, server, remote
):
    settled_server(server)

    refused = terminal("app", "discover", "web-1", "--folder", PROJECT_DIR)
    wrong = terminal(
        "app",
        "discover",
        "web-1",
        "--folder",
        PROJECT_DIR,
        "--password-stdin",
        stdin="not-it\n",
    )
    reached = list(remote.runs)
    found = terminal(
        "app",
        "discover",
        "web-1",
        "--folder",
        PROJECT_DIR,
        "--password-stdin",
        stdin=f"{PASSWORD}\n",
    )

    assert refused.code == 1 and "--password-stdin" in refused.err
    assert wrong.code == 1 and reached == []
    assert found.code == 0, found.err
    assert PYTHON in found.out


@pytest.mark.django_db
def test_add_adds_the_place_found_and_checks_it(terminal, admin, server, remote):
    ran = adding(terminal)

    assert ran.code == 0, ran.err
    lines = ran.out.splitlines()
    assert lines[0] == f"Added shop: {PROJECT_DIR}."
    assert lines[1].split() == CHECK_COLUMNS
    assert lines[2].split()[:5] == ["shop", "web-1", "online", "ok", REMOTE_VERSION]
    application = ApplicationRepository().active().get(name="shop")
    assert application.server_id == server.pk
    assert (application.kind, application.engine) == (Application.Kind.HOST, "")
    assert (application.project_dir, application.python_path) == (PROJECT_DIR, PYTHON)
    assert application.settings_module == SETTINGS_MODULE
    assert (application.env_path, application.remote_backup_dir) == (
        ENV_PATH,
        BACKUP_DIR,
    )
    assert application.discovered_at is not None
    assert application.has_backup_passphrase
    assert application.last_check_status == Application.CheckStatus.OK
    assert [entry.actor for entry in logged("application.create")] == [admin]
    assert [entry.actor for entry in logged("application.check")] == [admin]


@pytest.mark.django_db
def test_settings_given_to_add_replace_what_was_found(terminal, admin, server, remote):
    ran = adding(
        terminal,
        "--password-stdin",
        "--settings",
        "config.settings.staging",
        "--file-root",
        "/srv/app/media",
        "--file-root",
        "/srv/app/static",
        stdin=f"{PASSWORD}\n",
    )

    assert ran.code == 1, ran.err
    application = ApplicationRepository().active().get(name="shop")
    assert application.settings_module == "config.settings.staging"
    assert application.file_roots == ["/srv/app/media", "/srv/app/static"]
    assert application.python_path == PYTHON
    assert "/srv/app/media is missing" in ran.out


@pytest.mark.django_db
def test_changing_what_runs_while_adding_asks_for_the_password(
    terminal, admin, server, remote
):
    ran = adding(terminal, "--python", "/usr/bin/python3")

    assert ran.code != 0
    assert "--password-stdin" in ran.err
    assert not ApplicationRepository().active().exists()


@pytest.mark.django_db
def test_what_discovery_found_is_added_without_the_password(
    terminal, admin, server, remote
):
    ran = adding(terminal, "--file-root", "/srv/app/media")

    assert ApplicationRepository().active().filter(name="shop").exists(), ran.err


@pytest.mark.django_db
def test_add_json_holds_the_application_and_its_check(terminal, admin, server, remote):
    body = adding(terminal, "--json").json()

    assert body["name"] == "shop" and body["server"]["name"] == "web-1"
    assert body["project_dir"] == PROJECT_DIR
    assert body["check"]["last_check_status"] == "ok"
    assert body["check"]["remote_version"] == REMOTE_VERSION
    assert body["check"]["compatible"] is True


@pytest.mark.django_db
@pytest.mark.parametrize("chosen", ["0", "2"])
def test_a_candidate_that_was_not_found_is_a_clear_error(
    terminal, admin, server, remote, chosen
):
    ran = adding(terminal, "--candidate", chosen)

    assert ran.code == 1
    assert ran.err.strip() == "django_dbs: choose a candidate from 1 to 1."
    assert not ApplicationRepository().active().exists()


@pytest.mark.django_db
def test_add_in_a_folder_without_a_project_adds_nothing(
    terminal, admin, server, remote
):
    ran = terminal("app", "add", "shop", "--server", "web-1", "--folder", "/srv/empty")

    assert ran.code == 1
    assert ran.err.strip() == "django_dbs: found no Django project in /srv/empty."
    assert not ApplicationRepository().active().exists()


@pytest.mark.django_db
def test_add_reports_the_same_validation_as_the_api(
    terminal, api, admin, server, remote, make_application
):
    make_application(name="shop", host="10.0.0.6")

    ran = adding(terminal)
    answer = api.post(
        "/api/applications/",
        {"server": str(server.pk), "name": "shop", "project_dir": PROJECT_DIR},
        format="json",
    )

    error = answer.json()["error"]
    assert ran.code == 1 and answer.status_code == 400
    assert error["fields"] == {"name": ["name_taken"]}
    assert ran.err.strip() == f"django_dbs: name: {error['message']}"


@pytest.mark.django_db
def test_add_on_a_settled_server_asks_for_the_account_password(
    terminal, admin, server, remote
):
    settled_server(server)

    refused = adding(terminal)
    added = adding(terminal, "--password-stdin", stdin=f"{PASSWORD}\n")

    assert refused.code == 1 and "--password-stdin" in refused.err
    assert added.code == 0, added.err
    assert ApplicationRepository().active().get().name == "shop"


@pytest.mark.django_db
def test_check_all_reports_every_application_and_fails_if_one_does(
    terminal, admin, make_application, monkeypatch
):
    make_application(name="shop", host="10.0.0.5")
    make_application(name="blog", host="10.0.0.6")
    healthy = connecting_to(ready_remote())
    broken = refusing_with(SSHUnreachable())
    monkeypatch.setattr(
        CONNECT,
        lambda credentials: (broken if credentials.host == "10.0.0.6" else healthy)(
            credentials
        ),
    )

    ran = terminal("app", "check", "--all")

    assert ran.code == 1
    lines = ran.out.splitlines()
    assert lines[0].split() == CHECK_COLUMNS
    rows = {line.split()[0]: line for line in lines[1:]}
    assert rows["shop"].split()[1:5] == ["shop", "online", "ok", REMOTE_VERSION]
    assert "offline (ssh_unreachable)" in rows["blog"] and " failed " in rows["blog"]
    statuses = dict(
        ApplicationRepository().active().values_list("name", "last_check_status")
    )
    assert statuses == {"shop": "ok", "blog": "failed"}


@pytest.mark.django_db
def test_check_json_names_the_versions(terminal, admin, make_application, remote):
    make_application()

    [checked] = terminal("app", "check", "web-1", "--json").json()

    assert checked["last_check_status"] == "ok"
    assert checked["remote_version"] == REMOTE_VERSION
    assert checked["compatible"] is True


@pytest.mark.django_db
def test_check_names_the_python_that_has_django_dbs(
    terminal, admin, make_application, remote
):
    make_application(python_path="python3")

    ran = terminal("app", "check", "web-1")

    assert ran.code == 1
    assert f"set the application's Python to {PYTHON}" in ran.out


@pytest.mark.django_db
def test_check_needs_applications_or_all(terminal, admin, make_application):
    make_application()

    assert "choose all of them" in terminal("app", "check").err
    assert "not both" in terminal("app", "check", "web-1", "--all").err
    assert "no application named 'nope'" in terminal("app", "check", "nope").err


@pytest.mark.django_db
def test_editing_a_checked_applications_paths_asks_for_the_account_password(
    terminal, admin, make_application
):
    application = settled(make_application())

    refused = terminal("app", "edit", "web-1", "--python", "/usr/bin/python3")
    wrong = terminal(
        "app",
        "edit",
        "web-1",
        "--python",
        "/usr/bin/python3",
        "--password-stdin",
        stdin="not-it\n",
    )
    saved = terminal(
        "app",
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
    application.refresh_from_db()
    assert application.python_path == "/usr/bin/python3"


@pytest.mark.django_db
def test_renaming_an_application_needs_no_password(terminal, admin, make_application):
    settled(make_application())

    assert terminal("app", "edit", "web-1", "--name", "shop").code == 0
    assert ApplicationRepository().active().get().name == "shop"


@pytest.mark.django_db
def test_a_compose_application_needs_its_service(terminal, admin, make_application):
    make_application()

    ran = terminal("app", "edit", "web-1", "--kind", "compose", "--engine", "docker")

    assert ran.code == 1
    assert (
        "compose service: Name the Compose service that runs the application."
        in ran.err
    )
    assert ApplicationRepository().active().get().kind == Application.Kind.HOST


@pytest.mark.django_db
def test_remove_needs_the_name_typed_or_yes_and_the_password(
    terminal, admin, make_application, typing
):
    make_application(name="shop")
    make_application(name="blog", host="10.0.0.6")
    typing.append("sho")

    assert terminal("app", "remove", "shop").code == 1
    typing.extend(["shop", PASSWORD])
    assert terminal("app", "remove", "shop").code == 0
    no_password = terminal(
        "app", "remove", "blog", "--yes", "--password-stdin", stdin="\n"
    )
    assert no_password.code == 1
    assert ApplicationRepository().active().filter(name="blog").exists()
    removed = terminal(
        "app", "remove", "blog", "--yes", "--password-stdin", stdin=f"{PASSWORD}\n"
    )
    assert removed.code == 0, removed.err
    assert not ApplicationRepository().active().exists()
    assert ServerRepository().active().count() == 2


@pytest.mark.django_db
def test_revealing_the_passphrase_needs_the_password(terminal, admin, make_application):
    make_application()

    refused = terminal("app", "passphrase", "web-1", "--password-stdin", stdin="x\n")
    shown = terminal(
        "app", "passphrase", "web-1", "--password-stdin", stdin=f"{PASSWORD}\n"
    )

    assert refused.code == 1
    assert shown.code == 0 and shown.out.strip() == BACKUP_PASSPHRASE
    assert [entry.actor for entry in logged("application.passphrase_reveal")] == [
        admin,
        admin,
    ]


@pytest.mark.django_db
def test_capturing_the_passphrase_reads_it_from_the_application(
    terminal, admin, make_application, remote
):
    application = make_application()
    remote.answers[(PYTHON, "manage.py", "dbs_key", "--show")] = Result(
        0, "captured-secret\n"
    )

    ran = terminal("app", "capture-passphrase", "web-1")

    assert ran.code == 0, ran.err
    assert "captured-secret" not in ran.out
    application.refresh_from_db()
    assert (
        ServerConnectionService(admin).backup_passphrase(application)
        == "captured-secret"
    )
