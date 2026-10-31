from __future__ import annotations

import json
import posixpath

import pytest

from dbs.manager.adapters.checks import problem
from dbs.manager.applications.models import Application
from dbs.manager.applications.repositories import ApplicationRepository
from dbs.manager.applications.services.discovery_service import (
    FIND_PROJECT,
    INSPECTED_FIELDS,
)
from dbs.manager.servers.gateways import EntryKind
from dbs.manager.servers.models import Server
from tests.manager.servers.support import (
    DBS_VERSION,
    PASSWORD,
    FakeRemote,
    Result,
    connecting_to,
)
from tests.manager.terminal.test_servers import REMOTE_VERSION, listed

CONNECT = "dbs.manager.servers.services.connection_service.connect"
FOLDER = "/srv/shop"
COMPOSE_FILES = ("compose.yaml", "compose.prod.yaml")
SERVICE = "backend"
CONTAINER_ID = "5f1c2a9b7d3e"
VENV_PYTHON = "/opt/venv/bin/python"
WORKDIR = "/app"
MANAGE = "/app/manage.py"
COMPOSE_SETTINGS = "shop.settings.prod"
CONTAINER_BACKUP_DIR = "/app/backups"
HOST_BACKUP_DIR = "/srv/shop/backups"
HOST_ENV = "/srv/shop/.env"
DOCKER_VERSION = "27.1.1"
COMPOSE_VERSION = "2.29.1"
EXEC_OPTIONS = ("-T", "-i")
EXEC_OPTIONS_WITH_VALUES = ("-u", "-w", "-e")
NOT_FOUND = Result(127, "", "exec: not found")
INSPECT = (
    "docker",
    "inspect",
    "--type",
    "container",
    "--format",
    INSPECTED_FIELDS,
    CONTAINER_ID,
)


def inspected(running: bool) -> str:
    return (
        json.dumps(
            {
                "Name": "/shop-backend-1",
                "State": {"Running": running},
                "Config": {
                    "Image": "shop:latest",
                    "Labels": {
                        "com.docker.compose.project": "shop",
                        "com.docker.compose.service": SERVICE,
                        "com.docker.compose.project.working_dir": FOLDER,
                        "com.docker.compose.project.config_files": ",".join(
                            posixpath.join(FOLDER, name) for name in COMPOSE_FILES
                        ),
                    },
                    "WorkingDir": WORKDIR,
                    "Env": [
                        "PATH=/opt/venv/bin:/usr/local/bin:/usr/bin:/bin",
                        f"DJANGO_SETTINGS_MODULE={COMPOSE_SETTINGS}",
                    ],
                },
                "Mounts": [
                    {
                        "Type": "bind",
                        "Source": HOST_BACKUP_DIR,
                        "Destination": CONTAINER_BACKUP_DIR,
                        "RW": True,
                    }
                ],
            }
        )
        + "\n"
    )


class ComposeProject(FakeRemote):
    def __init__(self, *, running: bool = True, manage_on_host: bool = False) -> None:
        super().__init__(
            answers={
                ("uname", "-sr"): Result(0, "Linux 6.1.0-18-amd64\n"),
                ("docker", "version", "--format", "{{.Server.Version}}"): Result(
                    0, f"{DOCKER_VERSION}\n"
                ),
                ("docker", "compose", "version", "--short"): Result(
                    0, f"{COMPOSE_VERSION}\n"
                ),
                ("docker", "ps", "--all", "--no-trunc", "--format", "{{.ID}}"): (
                    Result(0, f"{CONTAINER_ID}\n")
                ),
                INSPECT: Result(0, inspected(running)),
            },
            paths={HOST_BACKUP_DIR, HOST_ENV},
        )
        self.inside = {
            (VENV_PYTHON, "-c", DBS_VERSION): Result(0, f"{REMOTE_VERSION}\n"),
            (VENV_PYTHON, MANAGE, "dbs", "connection", "--json"): Result(
                0,
                json.dumps(
                    {"dbs_connection": 2, "remote_backup_dir": CONTAINER_BACKUP_DIR}
                ),
            ),
            (VENV_PYTHON, MANAGE, "dbs_backup", "--help"): Result(0, "usage\n"),
            (VENV_PYTHON, MANAGE, "dbs", "health", "--json"): Result(
                0, json.dumps({"status": "ok", "checks": []})
            ),
        }
        self.running = running
        self.files = (
            *COMPOSE_FILES,
            ".env",
            *(("manage.py",) if manage_on_host else ()),
        )
        self.composed: list[dict] = []
        self.executed: list[dict] = []

    def run(self, argv, **options):
        argv = list(argv)
        if argv[:2] == ["docker", "ps"] and "status=running" in argv:
            wanted = f"label=com.docker.compose.service={SERVICE}" in argv
            return Result(0, f"shop-{SERVICE}-1\n" if wanted and self.running else "")
        if argv[:2] != ["docker", "compose"] or argv[2:3] == ["version"]:
            return super().run(argv, **options)
        rest, files, project = argv[2:], [], ""
        while rest[0] in ("-f", "-p"):
            option, value = rest.pop(0), rest.pop(0)
            if option == "-f":
                files.append(value)
            else:
                project = value
        self.composed.append({"files": files, "project": project, "verb": rest[0]})
        if rest[0] == "ps":
            return Result(0, f"db\n{SERVICE}\n" if self.running else "db\n")
        if rest[0] != "exec":
            return NOT_FOUND
        service, command, settings = self.split(rest[1:])
        self.executed.append(
            {"service": service, "command": command, "settings": settings}
        )
        if service != SERVICE or not self.running:
            return Result(1, "", f'service "{service}" is not running')
        if command[:3] == [VENV_PYTHON, "-c", FIND_PROJECT]:
            found = {"manage": MANAGE, "folder": WORKDIR, "settings": COMPOSE_SETTINGS}
            return Result(0, json.dumps(found) + "\n")
        return self.inside.get(tuple(command), NOT_FOUND)

    def split(self, arguments: list[str]) -> tuple[str, list[str], str]:
        settings = ""
        while arguments[0] in EXEC_OPTIONS + EXEC_OPTIONS_WITH_VALUES:
            option = arguments.pop(0)
            if option in EXEC_OPTIONS_WITH_VALUES:
                value = arguments.pop(0)
                if value.startswith("DJANGO_SETTINGS_MODULE="):
                    settings = value.split("=", 1)[1]
        return arguments[0], arguments[1:], settings

    def listdir(self, folder):
        if folder == FOLDER:
            return [
                listed(posixpath.join(FOLDER, name), EntryKind.FILE)
                for name in self.files
            ]
        return []

    def read_small(self, path, limit):
        if path == posixpath.join(FOLDER, COMPOSE_FILES[0]):
            return f"services:\n  {SERVICE}:\n    env_file: .env\n".encode()
        return None


@pytest.fixture
def compose_project(monkeypatch):
    found = ComposeProject()
    monkeypatch.setattr(CONNECT, connecting_to(found))
    return found


@pytest.mark.django_db
def test_discover_finds_the_compose_service_that_runs_the_application(
    terminal, admin, make_server, compose_project
):
    make_server()

    ran = terminal("app", "discover", "web-1", "--folder", FOLDER)

    assert ran.code == 0, ran.err
    [candidate] = ran.out.splitlines()[2:]
    assert candidate.split() == [
        "1",
        "docker",
        "compose",
        SERVICE,
        VENV_PYTHON,
        REMOTE_VERSION,
        COMPOSE_SETTINGS,
        HOST_BACKUP_DIR,
        "-",
    ]


@pytest.mark.django_db
def test_discover_names_a_container_whose_details_were_cut_off(
    terminal, admin, make_server, compose_project
):
    make_server()
    compose_project.answers[INSPECT] = Result(
        0, inspected(True)[:100], stdout_truncated=True
    )

    ran = terminal("app", "discover", "web-1", "--folder", FOLDER)

    assert ran.code == 0, ran.err
    assert ran.out.splitlines()[-2:] == [
        "Found no Django project here.",
        f"Left out docker container {CONTAINER_ID}: "
        "it describes itself in more than 64 KiB.",
    ]
    shown = terminal("app", "discover", "web-1", "--folder", FOLDER, "--json")
    assert shown.json()["unread_containers"] == [
        {"engine": "docker", "id": CONTAINER_ID}
    ]


@pytest.mark.django_db
def test_add_a_compose_application_from_the_terminal_and_check_it(
    terminal, admin, make_server, compose_project
):
    make_server()

    ran = terminal("app", "add", "shop", "--server", "web-1", "--folder", FOLDER)

    assert ran.code == 0, ran.out + ran.err
    assert f"Added shop: docker compose {SERVICE}." in ran.out
    application = ApplicationRepository().active().get(name="shop")
    assert (application.kind, application.engine) == (
        Application.Kind.COMPOSE,
        Application.Engine.DOCKER,
    )
    assert (application.compose_project, application.compose_service) == (
        "shop",
        SERVICE,
    )
    assert application.compose_files == list(COMPOSE_FILES)
    assert (application.project_dir, application.workdir) == (FOLDER, WORKDIR)
    assert (application.python_path, application.manage_path) == (VENV_PYTHON, MANAGE)
    assert application.settings_module == COMPOSE_SETTINGS
    assert application.remote_backup_dir == CONTAINER_BACKUP_DIR
    assert application.mounts == [
        {
            "type": "bind",
            "source": HOST_BACKUP_DIR,
            "destination": CONTAINER_BACKUP_DIR,
            "rw": True,
        }
    ]
    assert (application.env_path, application.env_location) == (
        HOST_ENV,
        Application.EnvLocation.HOST,
    )
    assert application.last_check_status == Application.CheckStatus.OK
    assert application.last_check_report["container"]["running"] is True
    checked = [
        run
        for run in compose_project.executed
        if run["command"][1:] == [MANAGE, "dbs_backup", "--help"]
    ]
    assert checked and {run["settings"] for run in checked} == {COMPOSE_SETTINGS}

    shown = terminal("app", "show", "shop")
    assert "compose" in shown.out and SERVICE in shown.out


@pytest.mark.django_db
def test_settings_given_to_add_replace_what_was_found_in_the_service(
    terminal, admin, make_server, compose_project
):
    make_server()

    ran = terminal(
        "app",
        "add",
        "shop",
        "--server",
        "web-1",
        "--folder",
        FOLDER,
        "--compose-file",
        COMPOSE_FILES[1],
        "--settings",
        "shop.settings.staging",
        "--password-stdin",
        stdin=f"{PASSWORD}\n",
    )

    assert ran.code == 0, ran.out + ran.err
    application = ApplicationRepository().active().get(name="shop")
    assert application.compose_files == [COMPOSE_FILES[1]]
    assert application.settings_module == "shop.settings.staging"
    assert compose_project.composed[-1]["files"] == [COMPOSE_FILES[1]]
    assert [
        run["settings"]
        for run in compose_project.executed
        if run["command"][1:] == [MANAGE, "dbs_backup", "--help"]
    ] == ["shop.settings.staging"]


@pytest.mark.django_db
def test_the_candidate_chosen_is_the_one_added(
    terminal, admin, make_server, monkeypatch
):
    monkeypatch.setattr(CONNECT, connecting_to(ComposeProject(manage_on_host=True)))
    make_server()

    found = terminal("app", "discover", "web-1", "--folder", FOLDER, "--json").json()
    ran = terminal(
        "app",
        "add",
        "shop",
        "--server",
        "web-1",
        "--folder",
        FOLDER,
        "--candidate",
        "2",
    )

    assert [candidate["kind"] for candidate in found["candidates"]] == [
        "compose",
        "host",
    ]
    assert f"Added shop: {FOLDER}." in ran.out
    application = ApplicationRepository().active().get(name="shop")
    assert (application.kind, application.engine) == (Application.Kind.HOST, "")
    assert application.project_dir == FOLDER
    assert application.python_path == found["candidates"][1]["python_path"]


@pytest.mark.django_db
def test_a_stopped_service_is_found_and_named_as_a_problem(
    terminal, admin, make_server, monkeypatch
):
    monkeypatch.setattr(CONNECT, connecting_to(ComposeProject(running=False)))
    make_server()

    found = terminal("app", "discover", "web-1", "--folder", FOLDER, "--json").json()
    ran = terminal("app", "add", "shop", "--server", "web-1", "--folder", FOLDER)

    [candidate] = found["candidates"]
    assert candidate["running"] is False
    assert candidate["problems"] == ["container_not_running", "dbs_missing"]
    assert ran.code == 1
    assert f"{SERVICE} is not running" in ran.out
    application = ApplicationRepository().active().get(name="shop")
    assert application.last_check_status == Application.CheckStatus.PROBLEM


@pytest.mark.django_db
def test_a_compose_application_needs_its_service_from_the_terminal_too(
    terminal, admin, make_application
):
    make_application(name="shop")

    ran = terminal(
        "app",
        "edit",
        "shop",
        "--kind",
        "compose",
        "--engine",
        "docker",
        "--project-dir",
        FOLDER,
    )

    assert ran.code != 0
    assert (
        "compose service: Name the Compose service that runs the application."
        in ran.err
    )
    assert ApplicationRepository().active().get().kind == Application.Kind.HOST


def compose_application(**report) -> Application:
    return Application(
        name="shop",
        server=Server(name="web-1", username="deploy"),
        kind=Application.Kind.COMPOSE,
        engine=Application.Engine.DOCKER,
        compose_service=SERVICE,
        python_path="python",
        remote_backup_dir=CONTAINER_BACKUP_DIR,
        last_check_status=Application.CheckStatus.PROBLEM,
        last_check_report={
            "dbs_version": None,
            "backup_command": False,
            "remote_backup_dir": True,
            **report,
        },
    )


def test_a_stopped_service_is_the_one_problem_reported():
    application = compose_application(
        container={
            "engine": "docker",
            "version": COMPOSE_VERSION,
            "error": "",
            "running": False,
        }
    )

    assert problem(application) == f"{SERVICE} is not running"


def test_a_stopped_container_is_named_too():
    application = compose_application(
        container={
            "engine": "podman",
            "version": "5.2.0",
            "error": "",
            "running": False,
        }
    )
    application.kind = Application.Kind.CONTAINER
    application.engine = Application.Engine.PODMAN
    application.compose_service = ""
    application.container_name = "shop-web"

    assert problem(application) == "shop-web is not running"


def test_docker_that_does_not_run_says_why():
    application = compose_application(
        container={
            "engine": "docker",
            "version": None,
            "error": "permission denied while trying to connect to the Docker daemon socket",
            "running": False,
        }
    )

    assert problem(application) == (
        "docker does not run for deploy (permission denied while trying "
        "to connect to the Docker daemon socket)"
    )


def test_a_service_without_django_dbs_names_the_service():
    application = compose_application(
        container={
            "engine": "docker",
            "version": COMPOSE_VERSION,
            "error": "",
            "running": True,
        },
        backup_command=None,
    )

    assert problem(application) == (
        f"django-dbs is not installed for python in {SERVICE}"
    )
