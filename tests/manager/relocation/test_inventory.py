from __future__ import annotations

import json

import pytest

from dbs.manager.applications.services.facts import FACTS_MARKER
from dbs.manager.relocation import catalogue
from dbs.manager.relocation.inventory import Choice, Side, Survey, blocked, learn, spec_of
from dbs.manager.servers.gateways import RemoteHost
from dbs.manager.servers.services import ServerConnectionService
from tests.manager.factories import make_application, make_server
from tests.manager.remote import ScriptedSession

PROJECT = "/srv/shop"
WEB_ID = "sha256:" + "1" * 64
DB_ID = "sha256:" + "2" * 64


def container(name, service, image, image_id, mounts, ports=None, **host):
    return {
        "Id": name + "-id",
        "Name": "/" + name,
        "Image": image_id,
        "State": {"Running": True},
        "Config": {
            "Image": image,
            "Env": ["PATH=/usr/bin", "SECRET=s3"],
            "Labels": {
                "com.docker.compose.project": "shop" if service else "",
                "com.docker.compose.service": service,
            }
            if service
            else {},
        },
        "HostConfig": {"PortBindings": ports or {}, "NetworkMode": "bridge", **host},
        "Mounts": mounts,
        "NetworkSettings": {"Networks": {"bridge": {}}},
    }


COMPOSE_ROWS = [
    container(
        "shop-web-1",
        "web",
        "shop-web:latest",
        WEB_ID,
        [
            {"Type": "bind", "Source": f"{PROJECT}/media", "Destination": "/app/media", "RW": True},
            {"Type": "bind", "Source": "/srv/shared", "Destination": "/shared", "RW": True},
            {"Type": "volume", "Name": "shop_static", "Source": "/var/lib/docker/volumes/shop_static/_data", "Destination": "/app/static", "RW": True},
            {"Type": "bind", "Source": "/var/run/docker.sock", "Destination": "/var/run/docker.sock", "RW": True},
        ],
        ports={"8000/tcp": [{"HostIp": "", "HostPort": "8000"}]},
    ),
    container(
        "shop-db-1",
        "db",
        "postgres:16",
        DB_ID,
        [{"Type": "volume", "Name": "shop_pgdata", "Source": "/var/lib/docker/volumes/shop_pgdata/_data", "Destination": "/var/lib/postgresql/data", "RW": True}],
    ),
]


def answers(rows, database, *, target=False, engine_ready=True):
    def answer(argv, line):
        name = argv[0]
        if argv == ["id"]:
            return (0, "uid=1000(deploy) gid=1000(deploy)\n", "") if not target else (0, "uid=1001(ops) gid=1001(ops)\n", "")
        if argv == ["uname", "-m"]:
            return 0, "x86_64\n", ""
        if argv == ["sudo", "--version"]:
            return 0, "Sudo\n", ""
        if argv[:2] == ["sudo", "-n"]:
            return 1, "", "a password is required\n"
        if name == "du":
            return 0, f"1000\t{argv[-1]}\n", ""
        if name == "find":
            return 0, "", ""
        if name == "df":
            return 0, "Filesystem 1-blocks Used Available Capacity Mounted on\n" + "".join(
                "/dev/sda1 100 1 99999999999 1% /\n" for _ in argv[4:]
            ), ""
        if name == "dpkg-query":
            return 1, "", ""
        if name == "docker":
            if target and not engine_ready:
                return 127, "", "docker: not found"
            if argv[1] == "version":
                return 0, "27.1.1\n", ""
            if argv[1:3] == ["compose", "version"]:
                return 0, "2.29.1\n", ""
            if argv[1] == "ps":
                return 0, "\n".join(json.dumps({"ID": row["Id"]}) for row in rows) + "\n", ""
            if argv[1] == "inspect":
                return 0, json.dumps(rows), ""
            if argv[1:3] == ["image", "inspect"] and argv[3] == "--format":
                ref = argv[-1]
                if target:
                    return 1, "", "No such image"
                image_id = WEB_ID if ref.startswith("shop-web") else DB_ID
                return 0, f"{image_id} 5000000 amd64\n", ""
            if argv[1:3] == ["volume", "inspect"]:
                return (1, "", "no such volume") if target else (0, "/var/lib/docker/volumes/x/_data\n", "")
        if name == "docker" and argv[1] == "compose":
            if "shell" in argv:
                return 0, FACTS_MARKER + json.dumps(database) + "\n", ""
        if "shell" in argv and "-c" in argv:
            return 0, FACTS_MARKER + json.dumps(database) + "\n", ""
        return 127, "", f"{name}: not found"

    return answer


def side(host, rows, database, *, target=False, engine_ready=True):
    session = ScriptedSession(host, {})
    session.commands = Everything(answers(rows, database, target=target, engine_ready=engine_ready))
    return session


class Everything(dict):
    def __init__(self, handler):
        super().__init__()
        self.handler = handler

    def get(self, key, default=None):
        return self.handler

    def items(self):
        return [((), self.handler)]


@pytest.fixture
def survey(admin):
    def build(application, rows, database, *, engine_ready=False):
        source = learn(
            Side(
                RemoteHost(side("10.0.0.5", rows, database)),
                application.server,
                catalogue.PASSWORD,
            )
        )
        target_server = make_server(admin, name="new", host="10.0.0.6")
        target = learn(
            Side(
                RemoteHost(side("10.0.0.6", [], database, target=True, engine_ready=engine_ready)),
                target_server,
                catalogue.PASSWORD,
            )
        )
        return Survey(source, target, ServerConnectionService(admin))

    return build


POSTGRES_IN_COMPOSE = {
    "vendor": "postgresql",
    "engine": "django.db.backends.postgresql",
    "host": "db",
    "port": "5432",
    "name": "shop",
    "user": "shop",
    "caches": [],
    "broker": None,
}


@pytest.mark.django_db
def test_a_compose_project_carries_its_images_volumes_and_binds_but_not_its_database(admin, survey):
    application = make_application(
        admin,
        "shop",
        kind="compose",
        engine="docker",
        compose_project="shop",
        compose_service="web",
        project_dir=PROJECT,
        python_path="/usr/local/bin/python",
        backup_passphrase="x",
    )

    found = survey(application, COMPOSE_ROWS, POSTGRES_IN_COMPOSE).collect(
        [Choice(application=application, name="shop-new", folder=PROJECT)]
    )

    [plan] = found["applications"]
    assert plan["database"]["placement"] == "compose_service"
    assert plan["database"]["action"] == "restore"
    assert {image["ref"]: image["id"] for image in plan["images"]} == {
        "shop-web:latest": WEB_ID,
        "postgres:16": DB_ID,
    }
    assert {volume["name"]: (volume["selected"], volume["reason"]) for volume in plan["volumes"]} == {
        "shop_static": (True, ""),
        "shop_pgdata": (False, "database_volume"),
    }
    assert [volume["volume"] for volume in plan["volumes"]] == ["static", "pgdata"]
    assert [bind["source"] for bind in plan["binds"]] == ["/srv/shared"]
    assert plan["services"] == ["db", "web"]
    assert plan["ports"] == [8000]
    assert "docker" in plan["needs"]
    assert found["needs_sudo"]["target"] is True
    assert blocked(found) == [] or {item["code"] for item in blocked(found)} <= {"os_unsupported"}


@pytest.mark.django_db
def test_a_volume_the_developer_leaves_out_is_not_selected(admin, survey):
    application = make_application(
        admin,
        "shop",
        kind="compose",
        engine="docker",
        compose_project="shop",
        compose_service="web",
        project_dir=PROJECT,
        backup_passphrase="x",
    )

    found = survey(application, COMPOSE_ROWS, POSTGRES_IN_COMPOSE).collect(
        [
            Choice(
                application=application,
                name="shop-new",
                folder=PROJECT,
                skip_volumes=frozenset({"shop_static"}),
            )
        ]
    )

    [plan] = found["applications"]
    static = next(volume for volume in plan["volumes"] if volume["name"] == "shop_static")
    assert (static["selected"], static["reason"]) == (False, "skipped")


@pytest.mark.django_db
def test_a_database_elsewhere_is_shared_and_never_restored(admin, survey):
    application = make_application(
        admin,
        "shop",
        kind="compose",
        engine="docker",
        compose_project="shop",
        compose_service="web",
        project_dir=PROJECT,
        backup_passphrase="x",
    )

    found = survey(
        application, COMPOSE_ROWS[:1], {**POSTGRES_IN_COMPOSE, "host": "db.example.net"}
    ).collect([Choice(application=application, name="shop-new", folder=PROJECT)])

    [plan] = found["applications"]
    assert plan["database"]["action"] == "shared"
    assert {note["code"] for note in plan["notes"]} >= {"database_shared_with_source"}


@pytest.mark.django_db
def test_a_container_with_options_the_move_cannot_rebuild_blocks_it(admin, survey):
    rows = [
        container(
            "shop",
            "",
            "shop:1",
            WEB_ID,
            [],
            Privileged=True,
            CapAdd=["NET_ADMIN"],
        )
    ]
    application = make_application(
        admin,
        "shop",
        kind="container",
        engine="docker",
        container_name="shop",
        project_dir=PROJECT,
        backup_passphrase="x",
    )

    found = survey(application, rows, {**POSTGRES_IN_COMPOSE, "host": "db.example.net"}).collect(
        [Choice(application=application, name="shop-new", folder=PROJECT)]
    )

    [plan] = found["applications"]
    [refused] = [item for item in plan["blockers"] if item["code"] == "container_options_unsupported"]
    assert refused["options"] == ["privileged", "cap_add"]


def test_a_container_is_rebuilt_from_what_differs_from_its_image():
    row = container(
        "shop",
        "",
        "shop:1",
        WEB_ID,
        [{"Type": "volume", "Name": "shop_data", "Source": "/x", "Destination": "/data", "RW": False}],
        ports={"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8080"}]},
        RestartPolicy={"Name": "unless-stopped", "MaximumRetryCount": 0},
    )
    row["Config"]["Cmd"] = ["gunicorn", "shop.wsgi"]
    image = {"Env": ["PATH=/usr/bin"], "Cmd": ["python"], "WorkingDir": "/app"}

    spec = spec_of("docker", row, image, env_file="/home/ops/.dbs-staging/shop.env")

    assert catalogue.container_run(spec).argv == (
        "docker",
        "run",
        "--detach",
        "--name",
        "shop",
        "--env-file",
        "/home/ops/.dbs-staging/shop.env",
        "--publish",
        "127.0.0.1:8080:8000/tcp",
        "--volume",
        "shop_data:/data:ro",
        "--restart",
        "unless-stopped",
        "--",
        "shop:1",
        "gunicorn",
        "shop.wsgi",
    )
