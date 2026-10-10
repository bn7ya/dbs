from __future__ import annotations

import os
import subprocess
import sys

import pytest

import dbs
from dbs.manager.servers.gateways.ssh_gateway import build_script
from dbs.manager.servers.services import discovery_service
from dbs.manager.servers.services.pythons import VERSION_PROBE
from dbs.manager.servers.services import browse_service, pythons
from tests.manager.remote import scripted_hosts
from tests.manager.servers.support import PASSWORD

OTHER_ID = 4242
PLANTED_VERSION = "9.9.9"


def discover(server_id):
    return f"/api/servers/{server_id}/discover/"


def discovering(api, server, **body):
    return api.post(
        discover(server.pk), {"account_password": PASSWORD, **body}, format="json"
    )


def browse(server_id):
    return f"/api/servers/{server_id}/browse/"


def venv(folder, mode=0o755, owner=-1, group=-1):
    (folder / "bin").mkdir(parents=True)
    (folder / "pyvenv.cfg").write_text("home = /usr/bin\n")
    for path in (folder, folder / "bin"):
        path.chmod(mode)
        os.chown(path, owner, group)
    return f"{folder}/bin/python"


@pytest.fixture
def site(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    srv = tmp_path / "srv"
    app = srv / "app"
    app.mkdir(parents=True)
    (app / "manage.py").write_text("")
    for folder in (tmp_path, srv, app):
        folder.chmod(0o755)
    monkeypatch.chdir(home)
    monkeypatch.setattr(discovery_service, "SEARCH_ROOTS", (str(srv),))
    return {"home": home, "srv": srv, "app": app}


def planted_answers(hosts, *pythons):
    for python in pythons:
        hosts.answer(
            "10.0.0.5", [python, "-c", VERSION_PROBE], (0, f"{PLANTED_VERSION}\n", "")
        )


@pytest.mark.django_db
def test_a_virtualenv_others_can_write_is_never_run(
    api, configured_server, site, monkeypatch
):
    open_to_all = venv(site["srv"] / "shared-env", mode=0o777)
    shared_group = venv(site["srv"] / "team-env", mode=0o775, group=OTHER_ID)
    someone_elses = venv(site["srv"] / "their-env", owner=OTHER_ID)
    own = venv(site["app"] / "own-env")
    own_group = venv(site["app"] / "umask-env", mode=0o775)
    hosts = scripted_hosts(monkeypatch)
    planted_answers(hosts, open_to_all, shared_group, someone_elses)

    body = discovering(api, configured_server).json()

    assert body["candidates"]["python_paths"] == [own, own_group, "python3", "python"]
    assert body["dbs_version"] is None
    ran = {run["argv"][0] for run in hosts.runs("10.0.0.5")}
    assert ran.isdisjoint({open_to_all, shared_group, someone_elses})


@pytest.mark.django_db
def test_the_check_never_suggests_a_virtualenv_others_can_write(
    api, configured_server, site, monkeypatch
):
    from dbs.manager.servers.repositories import ServerRepository

    ServerRepository().update(configured_server, project_dir=str(site["app"]))
    planted = venv(site["srv"] / "shared-env", mode=0o777)
    hosts = scripted_hosts(monkeypatch)
    planted_answers(hosts, planted)

    report = api.post(f"/api/servers/{configured_server.pk}/check/").json()[
        "last_check_report"
    ]

    assert report["python_suggestion"] is None
    assert planted not in {run["argv"][0] for run in hosts.runs("10.0.0.5")}


@pytest.mark.django_db
def test_a_project_others_can_write_is_not_run_unless_the_developer_chose_it(
    api, configured_server, site, monkeypatch
):
    site["app"].chmod(0o777)
    hosts = scripted_hosts(monkeypatch)

    found = discovering(api, configured_server).json()

    assert found["project_dir"] == str(site["app"])
    assert all("manage.py" not in run["argv"] for run in hosts.runs("10.0.0.5"))

    discovering(api, configured_server, project_dir=str(site["app"]))

    assert any("manage.py" in run["argv"] for run in hosts.runs("10.0.0.5"))


@pytest.mark.django_db
def test_a_folder_name_with_shell_syntax_stays_one_argument(
    api, configured_server, site, monkeypatch, tmp_path
):
    hostile = venv(site["app"] / "x; touch pwned; #")
    hosts = scripted_hosts(monkeypatch)

    discovering(api, configured_server)

    assert [hostile, "-c", VERSION_PROBE] in [
        run["argv"] for run in hosts.runs("10.0.0.5")
    ]
    script = build_script([hostile, "-c", VERSION_PROBE], cwd=str(site["app"]))
    subprocess.run(script, shell=True, cwd=tmp_path, capture_output=True)
    assert not any(path.name == "pwned" for path in tmp_path.rglob("pwned"))


def test_the_version_probe_ignores_a_dbs_module_in_the_folder_it_runs_in(tmp_path):
    marker = tmp_path / "imported"
    (tmp_path / "dbs.py").write_text(
        f"open({str(marker)!r}, 'w').close()\n__version__ = {PLANTED_VERSION!r}\n"
    )
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}

    result = subprocess.run(
        [sys.executable, "-c", VERSION_PROBE],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == dbs.__version__
    assert not marker.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/srv/app\x00/etc", "srv/app", "/srv/../etc", "~/app"])
def test_browsing_and_discovery_refuse_a_path_that_is_not_plain_and_absolute(
    api, configured_server, monkeypatch, path
):
    hosts = scripted_hosts(monkeypatch)

    listed = api.get(browse(configured_server.pk), {"path": path})
    found = discovering(api, configured_server, project_dir=path)

    assert listed.status_code == 400 and found.status_code == 400
    assert hosts.sessions == []


@pytest.mark.django_db
def test_browsing_an_unknown_server_is_not_found(api, monkeypatch):
    scripted_hosts(monkeypatch)

    response = api.get(browse("00000000-0000-0000-0000-000000000000"))

    assert response.status_code == 404


@pytest.mark.django_db
def test_discovery_needs_the_csrf_token_of_the_session(admin, configured_server):
    from rest_framework.test import APIClient

    client = APIClient(enforce_csrf_checks=True)
    client.force_login(admin)

    response = client.post(discover(configured_server.pk), {}, format="json")

    assert response.status_code == 403


@pytest.mark.django_db
def test_after_setup_discovery_asks_for_the_password_before_it_connects(
    api, configured_server, site, monkeypatch
):
    hosts = scripted_hosts(monkeypatch)

    missing = api.post(discover(configured_server.pk), {}, format="json")
    wrong = discovering(api, configured_server, account_password="not-the-password")

    assert missing.status_code == 400
    assert missing.json()["error"]["fields"] == {"account_password": ["required"]}
    assert wrong.status_code == 400
    assert wrong.json()["error"]["code"] == "invalid_password"
    assert hosts.sessions == []
    assert discovering(api, configured_server).status_code == 200


@pytest.mark.django_db
def test_an_uploaded_manage_py_is_not_run_without_the_password(
    api, configured_server, site, monkeypatch
):
    from dbs.manager.servers.repositories import ServerRepository

    uploads = site["home"] / "uploads"
    uploads.mkdir()
    ServerRepository().update(configured_server, file_roots=[str(uploads)])
    hosts = scripted_hosts(monkeypatch)
    sent = api.post(
        f"/api/files/{configured_server.pk}/upload/",
        {"path": str(uploads), "file": _file("manage.py", b"import os\n")},
        format="multipart",
    )
    assert sent.status_code == 201

    refused = api.post(
        discover(configured_server.pk), {"project_dir": str(uploads)}, format="json"
    )

    assert refused.status_code == 400
    assert all("manage.py" not in run["argv"] for run in hosts.runs("10.0.0.5"))
    discovering(api, configured_server, project_dir=str(uploads))
    assert any("manage.py" in run["argv"] for run in hosts.runs("10.0.0.5"))


def _file(name, content):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(name, content)


@pytest.mark.django_db
def test_a_virtualenv_whose_parent_others_can_write_is_never_run(
    api, configured_server, site, monkeypatch
):
    open_parent = site["srv"] / "drop"
    open_parent.mkdir()
    planted = venv(open_parent / "env")
    open_parent.chmod(0o777)
    beside = venv(site["srv"] / "beside-env")
    hosts = scripted_hosts(monkeypatch)

    body = discovering(api, configured_server, project_dir=str(open_parent)).json()

    assert planted not in body["candidates"]["python_paths"]
    assert planted not in {run["argv"][0] for run in hosts.runs("10.0.0.5")}
    nearby = discovering(api, configured_server, project_dir=str(site["app"])).json()
    assert beside in nearby["candidates"]["python_paths"]


@pytest.mark.django_db
def test_a_found_project_under_a_folder_others_can_write_is_not_run(
    api, configured_server, site, monkeypatch
):
    site["srv"].chmod(0o777)
    hosts = scripted_hosts(monkeypatch)

    found = discovering(api, configured_server).json()

    assert found["project_dir"] == str(site["app"])
    assert all("manage.py" not in run["argv"] for run in hosts.runs("10.0.0.5"))


@pytest.mark.django_db
def test_browsing_a_huge_folder_keeps_only_the_first_entries(
    api, configured_server, site, monkeypatch
):
    monkeypatch.setattr(browse_service, "BROWSE_LIMIT", 3)
    for number in range(5):
        (site["home"] / f"file-{number}").write_text("")
    scripted_hosts(monkeypatch)

    body = api.get(browse(configured_server.pk), {"path": str(site["home"])}).json()

    assert body["truncated"] is True
    assert body["count"] == 3


@pytest.mark.django_db
def test_one_search_probes_a_bounded_number_of_pythons(
    api, configured_server, site, monkeypatch
):
    for number in range(12):
        venv(site["app"] / f"env-{number:02}")
    hosts = scripted_hosts(monkeypatch)

    discovering(api, configured_server)

    probed = [
        run["argv"][0]
        for run in hosts.runs("10.0.0.5")
        if run["argv"][1:] == ["-c", VERSION_PROBE]
    ]
    assert len(probed) == pythons.PROBES_PER_SEARCH
    assert probed[-2:] == ["python3", "python"]
