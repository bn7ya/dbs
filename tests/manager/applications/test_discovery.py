from __future__ import annotations

import json
import subprocess
import sys

import pytest

from dbs.manager.applications.repositories import ApplicationRepository
from dbs.manager.applications.services import discovery_service
from dbs.manager.applications.services.facts import DATABASE_FACTS
from dbs.manager.applications.services.discovery_service import (
    FIND_PROJECT,
    settings_of,
)
from dbs.manager.servers.services.pythons import VERSION_PROBE
from tests.manager.applications.support import Engines, Inside
from tests.manager.remote import scripted_hosts
from tests.manager.servers.support import PASSWORD
from tests.manager.support import logged

DISCOVER = "/api/applications/discover/"
SHOP_FILES = ["-f", "compose.yaml", "-f", "compose.prod.yaml", "-p", "shop"]
COMPOSE = """services:
  backend:
    image: registry.example.com/shop/backend:2026.10
    env_file:
      - .env
      - path: ../shared/shop.env
        required: false
    volumes:
      - ./media:/app/media
      - ./backups:/app/backups
      - static:/app/static
  worker:
    image: registry.example.com/shop/backend:2026.10
    env_file: [".env"]
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: shop
volumes:
  static:
"""
COMPOSE_PROD = """services:
  backend:
    deploy:
      replicas: 2
"""
WIKI_COMPOSE = """services:
  web:
    build: .
    volumes:
      - ./uploads:/usr/src/app/uploads
"""
SHOP_CONNECTION = {
    "dbs_connection": 2,
    "settings_module": "shop.settings.prod",
    "remote_backup_dir": "/app/backups",
    "file_roots": ["/app/media", "/app/static"],
    "env_path": "/app/.env",
    "dbs_version": "0.8.0",
}
WIKI_CONNECTION = {
    "dbs_connection": 1,
    "remote_backup_dir": "/var/backups/dbs",
    "file_roots": ["/usr/src/app/uploads"],
    "env_path": "/usr/src/app/wiki/.env",
    "dbs_version": "0.8.0",
}
DOCKER_SOCKET_REFUSED = (
    "permission denied while trying to connect to the Docker daemon socket at "
    "unix:///var/run/docker.sock"
)


def manage_py(settings: str) -> str:
    return f"import os\nos.environ.setdefault('DJANGO_SETTINGS_MODULE', '{settings}')\n"


@pytest.fixture
def site(tmp_path, monkeypatch):
    home = tmp_path / "home"
    srv = tmp_path / "srv"
    shop, blog, wiki = srv / "shop", srv / "blog", srv / "wiki"
    containers = tmp_path / "containers"
    for folder in (
        home,
        shop / "media",
        shop / "backups",
        srv / "shared",
        blog / "media",
        wiki / "uploads",
        containers / "backend" / "app",
        containers / "blog-web" / "code",
        containers / "web" / "usr" / "src" / "app" / "wiki",
    ):
        folder.mkdir(parents=True)
    (shop / "compose.yaml").write_text(COMPOSE)
    (shop / "compose.prod.yaml").write_text(COMPOSE_PROD)
    (shop / ".env").write_text("SECRET_KEY=x\n")
    (srv / "shared" / "shop.env").write_text("SENTRY_DSN=x\n")
    (blog / "manage.py").write_text(manage_py("blog.settings"))
    (blog / ".env").write_text("SECRET_KEY=y\n")
    (wiki / "podman-compose.yml").write_text(WIKI_COMPOSE)
    (containers / "backend" / "app" / "manage.py").write_text(
        manage_py("shop.settings")
    )
    (containers / "blog-web" / "code" / "manage.py").write_text(
        manage_py("blog.settings")
    )
    (containers / "web" / "usr" / "src" / "app" / "wiki" / "manage.py").write_text(
        manage_py("wiki.settings")
    )
    for folder in (tmp_path, srv, shop, blog, wiki, home):
        folder.chmod(0o755)
    monkeypatch.chdir(home)
    return {
        "root": tmp_path,
        "home": home,
        "srv": srv,
        "shop": shop,
        "blog": blog,
        "wiki": wiki,
        "containers": containers,
    }


@pytest.fixture
def hosts(monkeypatch):
    return scripted_hosts(monkeypatch)


@pytest.fixture
def docker(hosts, site):
    engines = Engines(hosts, site["root"])
    engines.rows = engines.offer(
        "docker",
        version="27.3.1",
        compose="2.29.7",
        ps="docker_ps.jsonl",
        inspect="docker_inspect.json",
    )
    containers = site["containers"]
    engines.place(
        "backend",
        Inside(
            root=containers / "backend",
            pythons={"/opt/venv/bin/python": "0.8.0"},
            connection=SHOP_CONNECTION,
        ),
    )
    engines.place("db", Inside(root=containers / "db"))
    engines.place(
        "blog-web", Inside(root=containers / "blog-web", pythons={"python3": "0.6.2"})
    )
    engines.place("blog-cron", Inside(root=containers / "blog-cron"))
    return engines


@pytest.fixture
def podman(hosts, site):
    engines = Engines(hosts, site["root"])
    engines.offer(
        "podman",
        version="5.2.2",
        compose="podman-compose version 1.2.0",
        ps="podman_ps.json",
        inspect="podman_inspect.json",
    )
    engines.place(
        "web",
        Inside(
            root=site["containers"] / "web",
            pythons={"/usr/src/app/.venv/bin/python": "0.8.0"},
            connection=WIKI_CONNECTION,
        ),
    )
    return engines


def discovered(api, server, folder, **body):
    response = api.post(
        DISCOVER,
        {
            "server": str(server.pk),
            "folder": str(folder),
            "account_password": PASSWORD,
            **body,
        },
        format="json",
    )
    assert response.status_code == 200, response.content
    return response.json()


def ran(hosts):
    return [run["argv"] for run in hosts.runs("10.0.0.5")]


def candidate(report, **match):
    [found] = [
        each
        for each in report["candidates"]
        if all(each[key] == value for key, value in match.items())
    ]
    return found


@pytest.mark.django_db
def test_a_compose_project_is_found_by_its_labels_and_ranked_by_what_it_can_do(
    api, server, site, docker
):
    report = discovered(api, server, site["shop"])

    assert report["folder"] == str(site["shop"])
    assert report["trusted"] is True
    assert report["listing"] == {
        "manage": False,
        "compose_files": ["compose.yaml"],
        "container_files": [],
        "env_files": [".env"],
    }
    assert [
        (each["kind"], each["compose_service"], each["score"], each["problems"])
        for each in report["candidates"]
    ] == [
        ("compose", "backend", 16, []),
        ("compose", "db", 3, ["dbs_missing"]),
        ("compose", "worker", 1, ["container_not_running", "dbs_missing"]),
    ]
    for each in report["candidates"]:
        assert (each["engine"], each["compose_project"]) == ("docker", "shop")
        assert each["compose_files"] == ["compose.yaml", "compose.prod.yaml"]
        assert each["project_dir"] == str(site["shop"])
        assert each["container_name"] == ""
    assert report["folders"] == []


@pytest.mark.django_db
def test_the_engines_are_reported_with_what_they_answered(api, server, site, docker):
    report = discovered(api, server, site["shop"])

    assert report["engines"] == {
        "docker": {
            "installed": True,
            "usable": True,
            "version": "27.3.1",
            "compose": "2.29.7",
            "error": "",
        },
        "podman": {
            "installed": False,
            "usable": False,
            "version": None,
            "compose": None,
            "error": "",
        },
    }


@pytest.mark.django_db
def test_containers_are_listed_in_full_and_inspected_by_id(
    api, server, site, docker, hosts
):
    discovered(api, server, site["shop"])

    argvs = ran(hosts)
    assert ["docker", "ps", "--all", "--no-trunc", "--format", "{{.ID}}"] in argvs
    [asked] = docker.inspected
    assert asked == [row["Id"] for row in docker.rows]


def padded(row, size):
    row["Config"]["Env"] = [*row["Config"]["Env"], "PADDING=" + "x" * size]


@pytest.mark.django_db
def test_containers_that_describe_themselves_in_more_than_64_kib_are_inspected_in_halves(
    api, server, site, docker
):
    for row in docker.rows:
        padded(row, 10_000)

    report = discovered(api, server, site["shop"])

    ids = [row["Id"] for row in docker.rows]
    assert docker.inspected == [ids, ids[:3], ids[3:]]
    assert [each["compose_service"] for each in report["candidates"]] == [
        "backend",
        "db",
        "worker",
    ]
    assert report["unread_containers"] == []


@pytest.mark.django_db
def test_a_container_that_alone_passes_64_kib_is_named_and_the_others_still_found(
    api, server, site, docker
):
    [redis] = [row for row in docker.rows if row["Name"] == "/redis"]
    padded(redis, 70_000)

    report = discovered(api, server, site["shop"])

    assert docker.inspected[-1] == [redis["Id"]]
    assert report["unread_containers"] == [{"engine": "docker", "id": redis["Id"]}]
    assert [each["compose_service"] for each in report["candidates"]] == [
        "backend",
        "db",
        "worker",
    ]


@pytest.mark.django_db
def test_a_container_gone_between_listing_and_inspecting_leaves_the_rest_found(
    api, server, site, docker, hosts
):
    [worker] = [row for row in docker.rows if row["Name"] == "/shop-worker-1"]
    docker.rows.remove(worker)
    inspect = docker.inspecting(docker.rows)

    def gone(argv, stdin_line):
        status, stdout, stderr = inspect(argv, stdin_line)
        return 1, stdout, f"Error response from daemon: No such container: {worker['Id']}"

    docker.answer(["docker", "inspect"], gone)

    report = discovered(api, server, site["shop"])

    assert [each["compose_service"] for each in report["candidates"]] == [
        "backend",
        "db",
    ]


@pytest.mark.django_db
def test_replicas_of_one_service_are_one_candidate(api, server, site, docker):
    report = discovered(api, server, site["shop"])

    backends = [
        each for each in report["candidates"] if each["compose_service"] == "backend"
    ]
    assert len(backends) == 1
    assert backends[0]["replicas"] == 2
    assert candidate(report, compose_service="db")["replicas"] == 1


@pytest.mark.django_db
def test_containers_that_belong_to_another_folder_are_left_out(
    api, server, site, docker
):
    report = discovered(api, server, site["shop"])

    assert {each["compose_service"] for each in report["candidates"]} == {
        "backend",
        "db",
        "worker",
    }
    assert all(each["container_name"] != "redis" for each in report["candidates"])


@pytest.mark.django_db
def test_the_service_is_asked_inside_for_its_python_project_and_connection(
    api, server, site, docker, hosts
):
    report = discovered(api, server, site["shop"])

    backend = candidate(report, compose_service="backend")
    assert backend["python_path"] == "/opt/venv/bin/python"
    assert backend["python_paths"][:2] == [
        "/opt/venv/bin/python",
        "/app/.venv/bin/python",
    ]
    assert (backend["manage_path"], backend["workdir"]) == ("/app/manage.py", "/app")
    assert backend["settings_module"] == "shop.settings.prod"
    assert (backend["dbs_version"], backend["compatible"]) == ("0.8.0", True)
    runs = [
        run
        for run in hosts.runs("10.0.0.5")
        if run["argv"][:2] == ["docker", "compose"] and "backend" in run["argv"]
    ]
    exec_prefix = ["docker", "compose", *SHOP_FILES, "exec", "-T"]
    assert [run["argv"] for run in runs] == [
        [*exec_prefix, "backend", "/opt/venv/bin/python", "-c", VERSION_PROBE],
        [
            *exec_prefix,
            "backend",
            "/opt/venv/bin/python",
            "-c",
            FIND_PROJECT,
            *dict.fromkeys(["/app", *discovery_service.PROJECT_FOLDERS]),
        ],
        [
            *exec_prefix,
            "-w",
            "/app",
            "-e",
            "DJANGO_SETTINGS_MODULE=shop.settings.prod",
            "backend",
            "/opt/venv/bin/python",
            "/app/manage.py",
            "dbs",
            "connection",
            "--json",
        ],
        [
            *exec_prefix,
            "-w",
            "/app",
            "-e",
            "DJANGO_SETTINGS_MODULE=shop.settings.prod",
            "backend",
            "/opt/venv/bin/python",
            "/app/manage.py",
            "shell",
            "-c",
            DATABASE_FACTS,
        ],
    ]
    assert all(run["setup"] == [f"cd {site['shop']} || exit 1"] for run in runs)


@pytest.mark.django_db
def test_container_paths_are_translated_to_the_host_through_its_mounts(
    api, server, site, docker
):
    backend = candidate(
        discovered(api, server, site["shop"]), compose_service="backend"
    )

    assert backend["mounts"] == [
        {
            "type": "bind",
            "source": str(site["shop"] / "media"),
            "destination": "/app/media",
            "rw": True,
        },
        {
            "type": "bind",
            "source": str(site["shop"] / "backups"),
            "destination": "/app/backups",
            "rw": True,
        },
        {
            "type": "volume",
            "source": "/var/lib/docker/volumes/shop_static/_data",
            "destination": "/app/static",
            "rw": True,
        },
    ]
    assert backend["file_roots"] == [
        {"path": "/app/media", "on_host": str(site["shop"] / "media")},
        {"path": "/app/static", "on_host": "/var/lib/docker/volumes/shop_static/_data"},
    ]
    assert backend["remote_backup_dir"] == "/app/backups"
    assert backend["backup_dir_on_host"] == str(site["shop"] / "backups")


@pytest.mark.django_db
def test_an_env_file_only_inside_the_image_is_kept_inside_the_container(
    api, server, site, docker
):
    backend = candidate(
        discovered(api, server, site["shop"]), compose_service="backend"
    )

    assert backend["env"][0] == {
        "path": "/app/.env",
        "location": "container",
        "source": "dbs",
    }


@pytest.mark.django_db
def test_an_env_file_a_mount_brings_from_the_host_is_used_on_the_host(
    api, server, site, docker
):
    docker.containers["backend"].connection = {
        **SHOP_CONNECTION,
        "env_path": "/app/media/settings.env",
    }

    backend = candidate(
        discovered(api, server, site["shop"]), compose_service="backend"
    )

    assert backend["env"][0] == {
        "path": str(site["shop"] / "media" / "settings.env"),
        "location": "host",
        "source": "dbs",
    }


@pytest.mark.django_db
def test_compose_env_files_are_offered_even_outside_the_folder(
    api, server, site, docker
):
    backend = candidate(
        discovered(api, server, site["shop"]), compose_service="backend"
    )

    assert backend["env"][1:] == [
        {"path": str(site["shop"] / ".env"), "location": "host", "source": "compose"},
        {
            "path": str(site["srv"] / "shared" / "shop.env"),
            "location": "host",
            "source": "compose",
        },
    ]


@pytest.mark.django_db
def test_an_env_file_named_by_an_override_compose_file_is_offered_too(
    api, server, site, docker
):
    (site["shop"] / "compose.prod.yaml").write_text(
        COMPOSE_PROD + "    env_file:\n      - prod.env\n"
    )

    backend = candidate(
        discovered(api, server, site["shop"]), compose_service="backend"
    )

    assert {
        "path": str(site["shop"] / "prod.env"),
        "location": "host",
        "source": "compose",
    } in backend["env"]


@pytest.mark.django_db
def test_a_stopped_container_is_offered_but_never_entered(
    api, server, site, docker, hosts
):
    worker = candidate(discovered(api, server, site["shop"]), compose_service="worker")

    assert worker["running"] is False
    assert (worker["python_path"], worker["python_paths"]) == ("", [])
    assert worker["settings_module"] == "shop.settings.prod"
    assert not [argv for argv in ran(hosts) if "worker" in argv]


@pytest.mark.django_db
def test_a_service_without_django_dbs_is_offered_with_the_problem(
    api, server, site, docker
):
    db = candidate(discovered(api, server, site["shop"]), compose_service="db")

    assert (db["dbs_version"], db["compatible"]) == (None, False)
    assert db["problems"] == ["dbs_missing"]
    assert db["python_path"] == db["python_paths"][0]
    assert docker.containers["db"].ran[-1][1:] == ["-c", VERSION_PROBE]


@pytest.mark.django_db
def test_a_plain_container_is_found_by_the_folder_it_mounts(api, server, site, docker):
    report = discovered(api, server, site["blog"])

    web = candidate(report, container_name="blog-web")
    assert (web["kind"], web["engine"]) == ("container", "docker")
    assert (web["compose_project"], web["compose_service"], web["compose_files"]) == (
        "",
        "",
        [],
    )
    assert (web["manage_path"], web["workdir"]) == ("/code/manage.py", "/code")
    assert web["settings_module"] == "blog.settings"
    assert web["python_path"] == "python3"
    assert web["project_dir"] == str(site["blog"])


@pytest.mark.django_db
def test_a_plain_container_is_asked_by_its_name_from_the_mounted_folder_first(
    api, server, site, docker, hosts
):
    discovered(api, server, site["blog"])

    finding = [argv for argv in ran(hosts) if FIND_PROJECT in argv]
    assert finding[0][:6] == [
        "docker",
        "exec",
        "blog-web",
        "python3",
        "-c",
        FIND_PROJECT,
    ]
    assert finding[0][6:] == list(
        dict.fromkeys(["/code", *discovery_service.PROJECT_FOLDERS])
    )


@pytest.mark.django_db
def test_a_django_dbs_too_old_is_named(api, server, site, docker):
    web = candidate(discovered(api, server, site["blog"]), container_name="blog-web")

    assert (web["dbs_version"], web["compatible"]) == ("0.6.2", False)
    assert web["problems"] == ["dbs_too_old"]


@pytest.mark.django_db
def test_two_containers_and_the_host_project_of_one_folder_are_ranked_together(
    api, server, site, docker
):
    report = discovered(api, server, site["blog"])

    assert [
        (each["kind"], each["container_name"], each["score"])
        for each in report["candidates"]
    ] == [
        ("container", "blog-web", 15),
        ("host", "", 4),
        ("container", "blog-cron", 3),
    ]
    host = candidate(report, kind="host")
    assert host["project_dir"] == str(site["blog"])
    assert host["env"] == [
        {"path": str(site["blog"] / ".env"), "location": "host", "source": "folder"}
    ]


@pytest.mark.django_db
def test_podman_compose_labels_are_read_as_well(api, server, site, podman, hosts):
    report = discovered(api, server, site["wiki"])

    [web] = report["candidates"]
    assert (web["kind"], web["engine"]) == ("compose", "podman")
    assert (web["compose_project"], web["compose_service"]) == ("wiki", "web")
    assert web["compose_files"] == ["podman-compose.yml"]
    assert web["project_dir"] == str(site["wiki"])
    assert web["python_path"] == "/usr/src/app/.venv/bin/python"
    assert (web["manage_path"], web["workdir"]) == (
        "/usr/src/app/wiki/manage.py",
        "/usr/src/app/wiki",
    )
    assert web["settings_module"] == "wiki.settings"
    [connection] = [argv for argv in ran(hosts) if argv[-2:] == ["connection", "--json"]]
    assert connection[:9] == [
        "podman",
        "compose",
        "-f",
        "podman-compose.yml",
        "-p",
        "wiki",
        "exec",
        "-T",
        "-w",
    ]
    assert report["engines"]["podman"]["compose"] == "podman-compose version 1.2.0"
    assert report["engines"]["docker"]["installed"] is False


@pytest.mark.django_db
def test_a_backup_folder_no_mount_reaches_is_a_problem(api, server, site, podman):
    [web] = discovered(api, server, site["wiki"])["candidates"]

    assert web["remote_backup_dir"] == "/var/backups/dbs"
    assert web["backup_dir_on_host"] is None
    assert web["problems"] == ["backup_dir_not_mounted"]
    assert web["file_roots"] == [
        {"path": "/usr/src/app/uploads", "on_host": str(site["wiki"] / "uploads")}
    ]
    assert web["env"] == [
        {"path": "/usr/src/app/wiki/.env", "location": "container", "source": "dbs"}
    ]


@pytest.mark.django_db
def test_an_engine_whose_socket_refuses_is_reported_and_never_searched(
    api, server, site, hosts
):
    engines = Engines(hosts, site["root"])
    engines.refuse("docker", 1, DOCKER_SOCKET_REFUSED)

    report = discovered(api, server, site["blog"])

    assert report["engines"]["docker"] == {
        "installed": True,
        "usable": False,
        "version": None,
        "compose": None,
        "error": "engine_permission_denied",
    }
    assert not [argv for argv in ran(hosts) if argv[:2] == ["docker", "ps"]]
    assert [each["kind"] for each in report["candidates"]] == ["host"]


@pytest.mark.django_db
def test_a_folder_with_no_container_and_no_project_has_no_candidate(
    api, server, site, docker
):
    empty = site["srv"] / "empty"
    empty.mkdir()
    empty.chmod(0o755)

    report = discovered(api, server, empty)

    assert report["trusted"] is True
    assert report["candidates"] == []


@pytest.mark.django_db
@pytest.mark.parametrize("opened", ["folder", "parent"])
def test_a_folder_others_can_write_runs_nothing(
    api, server, site, docker, hosts, opened
):
    (site["shop"] if opened == "folder" else site["srv"]).chmod(0o777)

    report = discovered(api, server, site["shop"])

    assert report["trusted"] is False
    assert (report["engines"], report["candidates"]) == ({}, [])
    assert ran(hosts) == []
    assert report["listing"]["compose_files"] == ["compose.yaml"]


@pytest.mark.django_db
def test_without_a_folder_discovery_suggests_folders_and_runs_nothing(
    api, server, site, hosts, monkeypatch
):
    (site["home"] / "app").mkdir()
    (site["home"] / "app" / "manage.py").write_text("")
    (site["home"] / ".cache" / "hidden").mkdir(parents=True)
    (site["home"] / ".cache" / "hidden" / "manage.py").write_text("")
    (site["srv"] / "a" / "b" / "c").mkdir(parents=True)
    (site["srv"] / "a" / "b" / "c" / "manage.py").write_text("")
    monkeypatch.setattr(discovery_service, "SEARCH_ROOTS", ("~", str(site["srv"])))

    report = discovered(api, server, "")

    assert report["folders"] == [
        str(site["shop"]),
        str(site["wiki"]),
        str(site["home"] / "app"),
        str(site["blog"]),
    ]
    assert (report["folder"], report["trusted"], report["candidates"]) == (
        "",
        False,
        [],
    )
    assert ran(hosts) == []


@pytest.mark.django_db
def test_a_folder_that_is_not_there_gets_suggestions_too(
    api, server, site, hosts, monkeypatch
):
    monkeypatch.setattr(discovery_service, "SEARCH_ROOTS", (str(site["srv"]),))
    missing = site["root"] / "nowhere" / "app"

    report = discovered(api, server, missing)

    assert report["folder"] == str(missing)
    assert report["candidates"] == []
    assert report["folders"] == [
        str(site["shop"]),
        str(site["wiki"]),
        str(site["blog"]),
    ]
    assert ran(hosts) == []


@pytest.mark.django_db
def test_a_discovery_is_logged_against_the_server_with_what_it_found(
    api, server, site, docker
):
    discovered(api, server, site["shop"])

    [entry] = logged("application.discover")
    assert (entry.status, entry.subject, entry.target_name) == (
        "succeeded",
        str(server.pk),
        str(site["shop"]),
    )
    assert entry.data == {"folder": str(site["shop"]), "candidates": 3}


@pytest.mark.django_db
def test_after_setup_discovery_asks_for_the_password_before_it_connects(
    api, server, site, hosts
):
    missing = api.post(
        DISCOVER, {"server": str(server.pk), "folder": str(site["shop"])}, format="json"
    )
    wrong = api.post(
        DISCOVER,
        {
            "server": str(server.pk),
            "folder": str(site["shop"]),
            "account_password": "not-the-password",
        },
        format="json",
    )

    assert missing.status_code == 400
    assert missing.json()["error"]["fields"] == {"account_password": ["required"]}
    assert wrong.status_code == 400
    assert wrong.json()["error"]["code"] == "invalid_password"
    assert hosts.sessions == []
    [entry] = logged("application.discover")
    assert (entry.status, entry.error_code) == ("failed", "invalid_password")


@pytest.mark.django_db
def test_a_server_added_in_the_last_hour_is_searched_without_the_password(
    api, new_server, site, docker
):
    response = api.post(
        DISCOVER,
        {"server": str(new_server.pk), "folder": str(site["shop"])},
        format="json",
    )

    assert response.status_code == 200
    assert len(response.json()["candidates"]) == 3


@pytest.mark.django_db
@pytest.mark.parametrize(
    "folder", ["srv/app", "/srv/../etc", "~/app", "/srv/app\x00/etc"]
)
def test_a_folder_that_is_not_plain_and_absolute_is_refused(api, server, hosts, folder):
    response = api.post(
        DISCOVER,
        {"server": str(server.pk), "folder": folder, "account_password": PASSWORD},
        format="json",
    )

    assert response.status_code == 400
    assert hosts.sessions == []


@pytest.mark.django_db
def test_an_unknown_server_is_not_found(api, hosts):
    response = api.post(
        DISCOVER,
        {"server": "00000000-0000-0000-0000-000000000000", "folder": "/srv"},
        format="json",
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_the_chosen_candidate_becomes_an_application_as_found(
    api, server, site, docker
):
    report = discovered(api, server, site["shop"])
    backend = candidate(report, compose_service="backend")

    body = {
        **settings_of(backend, "shop"),
        "server": str(server.pk),
        "discovered": True,
        "account_password": PASSWORD,
    }
    response = api.post("/api/applications/", body, format="json")

    assert response.status_code == 201, response.content
    created = ApplicationRepository().get(response.json()["id"])
    assert (created.kind, created.engine) == ("compose", "docker")
    assert (created.compose_project, created.compose_service) == ("shop", "backend")
    assert created.compose_files == ["compose.yaml", "compose.prod.yaml"]
    assert (created.project_dir, created.workdir) == (str(site["shop"]), "/app")
    assert (created.python_path, created.manage_path) == (
        "/opt/venv/bin/python",
        "/app/manage.py",
    )
    assert created.settings_module == "shop.settings.prod"
    assert created.remote_backup_dir == "/app/backups"
    assert created.file_roots == ["/app/media", "/app/static"]
    assert (created.env_path, created.env_location) == ("/app/.env", "container")
    assert created.mounts == backend["mounts"]
    assert created.discovered_at is not None


def test_the_settings_of_a_candidate_are_what_create_takes():
    found = {
        "kind": "container",
        "engine": "podman",
        "compose_project": "",
        "compose_service": "",
        "compose_files": [],
        "container_name": "blog-web",
        "project_dir": "/srv/blog",
        "workdir": "/code",
        "python_path": "",
        "manage_path": "/code/manage.py",
        "settings_module": "blog.settings",
        "remote_backup_dir": "",
        "mounts": [
            {"type": "bind", "source": "/srv/blog", "destination": "/code", "rw": True}
        ],
        "file_roots": [{"path": "/code/media", "on_host": "/srv/blog/media"}],
        "env": [],
    }

    fields = settings_of(found)

    assert fields == {
        "kind": "container",
        "engine": "podman",
        "compose_project": "",
        "compose_service": "",
        "compose_files": [],
        "container_name": "blog-web",
        "project_dir": "/srv/blog",
        "workdir": "/code",
        "python_path": "python3",
        "manage_path": "/code/manage.py",
        "settings_module": "blog.settings",
        "mounts": found["mounts"],
        "file_roots": ["/code/media"],
        "env_path": "",
        "env_location": "host",
    }
    assert settings_of({**found, "remote_backup_dir": "/code/backups"}, "blog") == {
        **fields,
        "remote_backup_dir": "/code/backups",
        "name": "blog",
    }
    assert fields["mounts"] is not found["mounts"]


@pytest.mark.parametrize(
    ("starts", "expected"),
    [
        (
            ["/app"],
            {"manage": "/app/manage.py", "folder": "/app", "settings": "a.settings"},
        ),
        (
            ["/srv"],
            {
                "manage": "/srv/one/two/manage.py",
                "folder": "/srv/one/two",
                "settings": "",
            },
        ),
        (
            ["/missing", "/opt", "/app"],
            {
                "manage": "/opt/b/manage.py",
                "folder": "/opt/b",
                "settings": "b.settings",
            },
        ),
        (["/hidden"], {}),
        (["/deep"], {}),
    ],
)
def test_the_project_search_inside_a_container_looks_two_folders_deep(
    tmp_path, starts, expected
):
    layout = {
        "app/manage.py": manage_py("a.settings"),
        "srv/one/two/manage.py": "",
        "opt/b/manage.py": manage_py("b.settings"),
        "hidden/.venv/manage.py": "",
        "deep/one/two/three/manage.py": "",
    }
    for path, content in layout.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(content)

    done = subprocess.run(
        [
            sys.executable,
            "-c",
            FIND_PROJECT,
            *(f"{tmp_path}{start}" for start in starts),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert done.returncode == 0
    found = json.loads(done.stdout.strip().splitlines()[-1].replace(str(tmp_path), ""))
    assert found == expected


UNREADABLE = """
import os
listed = os.listdir

def refusing(folder):
    if os.path.basename(folder) == "locked":
        raise PermissionError(13, "Permission denied", folder)
    return listed(folder)

os.listdir = refusing
"""


def test_a_folder_the_container_user_may_not_read_does_not_end_the_search(tmp_path):
    (tmp_path / "srv" / "locked").mkdir(parents=True)
    (tmp_path / "usr" / "src" / "app").mkdir(parents=True)
    (tmp_path / "usr" / "src" / "app" / "manage.py").write_text(manage_py("c.settings"))

    done = subprocess.run(
        [
            sys.executable,
            "-c",
            UNREADABLE + FIND_PROJECT,
            f"{tmp_path}/srv",
            f"{tmp_path}/usr/src/app",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert done.returncode == 0, done.stderr
    found = json.loads(done.stdout.strip().splitlines()[-1].replace(str(tmp_path), ""))
    assert found == {
        "manage": "/usr/src/app/manage.py",
        "folder": "/usr/src/app",
        "settings": "c.settings",
    }


@pytest.mark.django_db
def test_a_search_enters_a_bounded_number_of_containers(
    api, server, site, docker, hosts, monkeypatch
):
    monkeypatch.setattr(discovery_service, "CANDIDATES_PROBED", 1)

    report = discovered(api, server, site["shop"])

    assert [each["compose_service"] for each in report["candidates"]] == ["backend"]
    assert docker.containers["db"].ran == []
    assert not [argv for argv in ran(hosts) if "db" in argv]


def inspected_row(name="shop-backend-1", project="shop", service="backend", **config):
    return {
        "Name": f"/{name}",
        "State": {"Running": True},
        "Config": {
            "Labels": {
                "com.docker.compose.project": project,
                "com.docker.compose.service": service,
                "com.docker.compose.project.working_dir": "/srv/shop",
                "com.docker.compose.project.config_files": "/srv/shop/compose.yaml",
            },
            **config,
        },
    }


def test_a_container_named_as_it_should_be_is_kept():
    assert discovery_service.well_named(discovery_service.summary("docker", inspected_row()))


@pytest.mark.parametrize(
    "row",
    [
        inspected_row(name="-u0"),
        inspected_row(service="-u"),
        inspected_row(project="--privileged"),
        inspected_row(service="web; id"),
        inspected_row(WorkingDir="-x"),
    ],
)
def test_a_container_whose_names_could_be_read_as_options_is_left_out(row):
    assert not discovery_service.well_named(discovery_service.summary("docker", row))



@pytest.mark.django_db
def test_answers_that_disagree_with_a_candidate_are_named(api, server, site, docker):
    report = discovered(
        api, server, site["shop"], deployment={"runs_in": "host", "engine": "docker"}
    )

    backend = candidate(report, compose_service="backend")
    assert backend["detected"]["runs_in"] == "compose"
    assert backend["mismatches"] == [
        {"field": "runs_in", "said": "host", "found": "compose"}
    ]
    assert backend["facts"]["image"]["ref"]


@pytest.mark.django_db
def test_a_candidate_that_matches_the_answers_comes_first(api, server, site, docker):
    plain = discovered(api, server, site["shop"])
    answered = discovered(api, server, site["shop"], deployment={"runs_in": "compose"})

    scores = {each["compose_service"]: each["score"] for each in plain["candidates"]}
    for each in answered["candidates"]:
        assert each["score"] == scores[each["compose_service"]] + 4


@pytest.mark.django_db
def test_an_unknown_answer_is_refused_before_anything_runs(api, server, site, hosts):
    response = api.post(
        DISCOVER,
        {
            "server": str(server.pk),
            "folder": str(site["shop"]),
            "account_password": PASSWORD,
            "deployment": {"runs_in": "kubernetes"},
        },
        format="json",
    )

    assert response.status_code == 400
    assert hosts.runs("10.0.0.5") == []
