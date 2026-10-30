from __future__ import annotations

import json

import pytest

from dbs.manager.servers.services.pythons import VERSION_PROBE
from tests.manager.applications.support import Engines, Inside
from tests.manager.remote import scripted_hosts
from tests.manager.servers.support import PASSWORD

DISCOVER = "/api/applications/discover/"


@pytest.fixture
def project(tmp_path, monkeypatch):
    home = tmp_path / "home"
    app = home / "app"
    (app / ".venv" / "bin").mkdir(parents=True)
    (app / ".venv" / "bin" / "python").write_text("")
    (app / "manage.py").write_text(
        "import os\n"
        "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shop.settings.prod')\n"
    )
    (app / ".env").write_text("SECRET_KEY=x\n")
    (app / ".env.example").write_text("SECRET_KEY=\n")
    sites = tmp_path / "srv" / "sites"
    (sites / "blog").mkdir(parents=True)
    (sites / "blog" / "manage.py").write_text("")
    for folder in (tmp_path, tmp_path / "srv", sites, home):
        folder.chmod(0o755)
    monkeypatch.chdir(home)
    return {"root": tmp_path, "home": home, "app": app, "sites": sites}


@pytest.fixture
def hosts(monkeypatch):
    return scripted_hosts(monkeypatch)


def discovered(api, server, folder):
    response = api.post(
        DISCOVER,
        {"server": str(server.pk), "folder": str(folder), "account_password": PASSWORD},
        format="json",
    )
    assert response.status_code == 200, response.content
    return response.json()


def ran(hosts):
    return hosts.runs("10.0.0.5")


@pytest.mark.django_db
def test_a_project_on_the_host_is_found_over_sftp(api, server, project, hosts):
    report = discovered(api, server, project["app"])

    app = str(project["app"])
    assert report["listing"] == {
        "manage": True,
        "compose_files": [],
        "container_files": [],
        "env_files": [".env", ".env.example"],
    }
    assert report["candidates"] == [
        {
            "kind": "host",
            "engine": "",
            "compose_project": "",
            "compose_service": "",
            "compose_files": [],
            "container_name": "",
            "replicas": 1,
            "running": True,
            "project_dir": app,
            "workdir": "",
            "python_path": f"{app}/.venv/bin/python",
            "python_paths": [f"{app}/.venv/bin/python", "python3", "python"],
            "manage_path": "manage.py",
            "settings_module": "shop.settings.prod",
            "remote_backup_dir": "",
            "mounts": [],
            "file_roots": [],
            "env": [
                {"path": f"{app}/.env", "location": "host", "source": "folder"},
                {"path": f"{app}/.env.example", "location": "host", "source": "folder"},
            ],
            "dbs_version": None,
            "backup_dir_on_host": None,
            "compatible": False,
            "problems": ["dbs_missing"],
            "score": 4,
            "facts": {
                "database": None,
                "placement": "",
                "git": None,
                "image": None,
                "services": [],
                "env_source": "folder_env",
                "folder_read": True,
            },
            "detected": {
                "runs_in": "host",
                "settings_from": "folder_env",
                "source": "copied",
            },
            "mismatches": [],
        }
    ]
    assert all("manage.py" not in run["argv"] for run in ran(hosts))


@pytest.mark.django_db
def test_every_python_is_probed_in_the_project_folder(api, server, project, hosts):
    discovered(api, server, project["app"])

    app = str(project["app"])
    probes = [run for run in ran(hosts) if run["argv"][1:] == ["-c", VERSION_PROBE]]
    assert [run["argv"][0] for run in probes] == [
        f"{app}/.venv/bin/python",
        "python3",
        "python",
    ]
    assert all(run["setup"] == [f"cd {app} || exit 1"] for run in probes)


@pytest.mark.django_db
def test_discovery_prefers_what_the_project_says_about_itself(
    api, server, project, hosts
):
    app = str(project["app"])
    venv = f"{app}/.venv/bin/python"
    details = {
        "dbs_connection": 1,
        "hostname": "web-1",
        "ssh_user": "deploy",
        "project_dir": app,
        "python_path": "/opt/py/bin/python",
        "manage_path": "manage.py",
        "settings_module": "shop.settings.live",
        "remote_backup_dir": "/var/backups/shop",
        "file_roots": ["/srv/media"],
        "env_path": "/etc/shop.env",
        "dbs_version": "0.8.0",
        "host_keys": [{"type": "ssh-ed25519", "fingerprint": "SHA256:abc"}],
    }
    hosts.answer("10.0.0.5", [venv, "-c", VERSION_PROBE], (0, "0.8.0\n", ""))
    hosts.answer(
        "10.0.0.5",
        [venv, "manage.py", "dbs", "connection", "--json"],
        (0, json.dumps(details), ""),
    )

    [found] = discovered(api, server, project["app"])["candidates"]

    assert found["python_path"] == venv
    assert found["settings_module"] == "shop.settings.live"
    assert found["remote_backup_dir"] == "/var/backups/shop"
    assert found["backup_dir_on_host"] == "/var/backups/shop"
    assert found["file_roots"] == [{"path": "/srv/media", "on_host": "/srv/media"}]
    assert found["env"][0] == {
        "path": "/etc/shop.env",
        "location": "host",
        "source": "dbs",
    }
    assert (found["dbs_version"], found["compatible"], found["problems"]) == (
        "0.8.0",
        True,
        [],
    )
    assert found["score"] == 15
    [last] = [run for run in ran(hosts) if run["argv"][-1] == "--json"]
    assert last["argv"] == [venv, "manage.py", "dbs", "connection", "--json"]
    assert last["setup"] == [
        f"cd {app} || exit 1",
        "export DJANGO_SETTINGS_MODULE=shop.settings.prod",
    ]


@pytest.mark.django_db
def test_an_answer_that_is_not_a_dbs_connection_is_ignored(api, server, project, hosts):
    venv = f"{project['app']}/.venv/bin/python"
    hosts.answer("10.0.0.5", [venv, "-c", VERSION_PROBE], (0, "0.8.0\n", ""))
    hosts.answer(
        "10.0.0.5",
        [venv, "manage.py", "dbs", "connection", "--json"],
        (0, json.dumps({"remote_backup_dir": "/etc", "settings_module": "x.y"}), ""),
    )

    [found] = discovered(api, server, project["app"])["candidates"]

    assert found["remote_backup_dir"] == ""
    assert found["settings_module"] == "shop.settings.prod"


@pytest.mark.django_db
def test_a_virtualenv_of_any_name_that_has_django_dbs_is_chosen(
    api, server, project, hosts
):
    app = project["app"]
    (app / "shop-env" / "bin").mkdir(parents=True)
    (app / "shop-env" / "pyvenv.cfg").write_text("home = /usr/bin\n")
    venv = f"{app}/shop-env/bin/python"
    hosts.answer("10.0.0.5", [venv, "-c", VERSION_PROBE], (0, "0.8.0\n", ""))

    [found] = discovered(api, server, app)["candidates"]

    assert found["python_path"] == venv
    assert found["dbs_version"] == "0.8.0"
    assert found["python_paths"] == [
        f"{app}/.venv/bin/python",
        venv,
        "python3",
        "python",
    ]
    assert [run["argv"][:3] for run in ran(hosts) if "manage.py" in run["argv"]][
        0
    ] == [venv, "manage.py", "dbs"]


@pytest.mark.django_db
def test_a_project_one_folder_down_is_found_from_its_parent(
    api, server, project, hosts
):
    hosts.answer("10.0.0.5", ["python3", "-c", VERSION_PROBE], (0, "0.8.0\n", ""))

    report = discovered(api, server, project["sites"])

    assert report["listing"]["manage"] is False
    [found] = report["candidates"]
    assert found["project_dir"] == str(project["sites"] / "blog")
    assert (found["python_path"], found["dbs_version"]) == ("python3", "0.8.0")


@pytest.mark.django_db
def test_the_host_project_outranks_a_service_without_django_dbs(
    api, server, project, hosts
):
    shop = project["root"] / "srv" / "shop"
    shop.mkdir()
    shop.chmod(0o755)
    (shop / "manage.py").write_text("")
    (shop / "compose.yaml").write_text("services: {}\n")
    engines = Engines(hosts, project["root"])
    engines.offer(
        "docker",
        version="27.3.1",
        compose="2.29.7",
        ps="docker_ps.jsonl",
        inspect="docker_inspect.json",
    )
    engines.place("backend", Inside(root=project["root"] / "containers" / "backend"))
    hosts.answer("10.0.0.5", ["python3", "-c", VERSION_PROBE], (0, "0.8.0\n", ""))

    report = discovered(api, server, shop)

    assert [
        (each["kind"], each["compose_service"]) for each in report["candidates"]
    ] == [
        ("host", ""),
        ("compose", "backend"),
        ("compose", "db"),
        ("compose", "worker"),
    ]
    assert report["candidates"][0]["dbs_version"] == "0.8.0"
    assert report["candidates"][1]["problems"] == ["dbs_missing"]


@pytest.mark.django_db
def test_a_folder_with_containers_but_no_manage_py_offers_no_host_project(
    api, server, project, hosts
):
    shop = project["root"] / "srv" / "shop"
    (shop / "backend").mkdir(parents=True)
    shop.chmod(0o755)
    (shop / "backend" / "manage.py").write_text("")
    engines = Engines(hosts, project["root"])
    engines.offer(
        "docker",
        version="27.3.1",
        ps="docker_ps.jsonl",
        inspect="docker_inspect.json",
    )

    report = discovered(api, server, shop)

    assert {each["kind"] for each in report["candidates"]} == {"compose"}
