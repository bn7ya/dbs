from __future__ import annotations

import os
import subprocess
from dataclasses import replace

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from dbs.manager.applications.repositories import ApplicationRepository
from dbs.manager.servers.gateways import RemoteHost
from dbs.manager.servers.gateways.ssh_gateway import build_script
from dbs.manager.servers.services import pythons
from dbs.manager.servers.services.pythons import VERSION_PROBE
from tests.manager.factories import make_application
from tests.manager.remote import scripted_hosts
from tests.manager.servers.support import PASSWORD

DISCOVER = "/api/applications/discover/"
OTHER_ID = 4242
PLANTED_VERSION = "9.9.9"


def discovering(api, server, folder, **body):
    return api.post(
        DISCOVER,
        {
            "server": str(server.pk),
            "folder": str(folder),
            "account_password": PASSWORD,
            **body,
        },
        format="json",
    )


def venv(folder, mode=0o755):
    (folder / "bin").mkdir(parents=True)
    (folder / "pyvenv.cfg").write_text("home = /usr/bin\n")
    for path in (folder, folder / "bin"):
        path.chmod(mode)
    return f"{folder}/bin/python"


def owned_by_another(monkeypatch, python, *, uid=None, gid=None):
    bin_folder = os.path.dirname(python)
    marked = {bin_folder, os.path.dirname(bin_folder)}
    listed = RemoteHost.lstat

    def lstat(self, path):
        entry = listed(self, path)
        if path not in marked:
            return entry
        return replace(
            entry,
            uid=entry.uid if uid is None else uid,
            gid=entry.gid if gid is None else gid,
        )

    monkeypatch.setattr(RemoteHost, "lstat", lstat)


@pytest.fixture
def site(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    srv = tmp_path / "srv"
    app = srv / "app"
    app.mkdir(parents=True)
    (app / "manage.py").write_text("")
    for folder in (tmp_path, srv, app, home):
        folder.chmod(0o755)
    monkeypatch.chdir(home)
    return {"home": home, "srv": srv, "app": app}


@pytest.fixture
def hosts(monkeypatch):
    return scripted_hosts(monkeypatch)


def planted_answers(hosts, *pythons):
    for python in pythons:
        hosts.answer(
            "10.0.0.5", [python, "-c", VERSION_PROBE], (0, f"{PLANTED_VERSION}\n", "")
        )


def ran(hosts):
    return [run["argv"] for run in hosts.runs("10.0.0.5")]


@pytest.mark.django_db
def test_a_virtualenv_others_can_write_is_never_run(
    api, server, site, hosts, monkeypatch
):
    open_to_all = venv(site["srv"] / "shared-env", mode=0o777)
    shared_group = venv(site["srv"] / "team-env", mode=0o775)
    owned_by_another(monkeypatch, shared_group, gid=OTHER_ID)
    someone_elses = venv(site["srv"] / "their-env")
    owned_by_another(monkeypatch, someone_elses, uid=OTHER_ID)
    own = venv(site["app"] / "own-env")
    own_group = venv(site["app"] / "umask-env", mode=0o775)
    planted_answers(hosts, open_to_all, shared_group, someone_elses)

    [found] = discovering(api, server, site["app"]).json()["candidates"]

    assert found["python_paths"] == [own, own_group, "python3", "python"]
    assert found["dbs_version"] is None
    ran_first = {argv[0] for argv in ran(hosts)}
    assert ran_first.isdisjoint({open_to_all, shared_group, someone_elses})


@pytest.mark.django_db
def test_the_check_never_suggests_a_virtualenv_others_can_write(
    api, admin, server, site, hosts
):
    application = make_application(
        admin, name="shop", server=server, project_dir=str(site["app"])
    )
    planted = venv(site["srv"] / "shared-env", mode=0o777)
    planted_answers(hosts, planted)

    report = api.post(f"/api/applications/{application.pk}/check/").json()[
        "last_check_report"
    ]

    assert report["python_suggestion"] is None
    assert planted not in {argv[0] for argv in ran(hosts)}


@pytest.mark.django_db
def test_a_project_others_can_write_is_not_run_even_when_the_developer_names_it(
    api, server, site, hosts
):
    site["app"].chmod(0o777)
    planted_answers(hosts, "python3")

    report = discovering(api, server, site["app"]).json()

    assert report["trusted"] is False
    assert report["listing"]["manage"] is True
    assert report["candidates"] == []
    assert ran(hosts) == []


@pytest.mark.django_db
def test_a_project_found_below_a_trusted_folder_that_others_can_write_is_not_run(
    api, server, site, hosts
):
    site["app"].chmod(0o777)
    planted_answers(hosts, "python3")

    report = discovering(api, server, site["srv"]).json()

    assert report["trusted"] is True
    [found] = report["candidates"]
    assert found["project_dir"] == str(site["app"])
    assert found["dbs_version"] is None
    assert all("manage.py" not in argv for argv in ran(hosts))
    assert all(argv[1:] != ["-c", VERSION_PROBE] for argv in ran(hosts))


@pytest.mark.django_db
def test_a_folder_name_with_shell_syntax_stays_one_argument(
    api, server, site, hosts, tmp_path
):
    hostile = venv(site["app"] / "x; touch pwned; #")

    discovering(api, server, site["app"])

    assert [hostile, "-c", VERSION_PROBE] in ran(hosts)
    script = build_script([hostile, "-c", VERSION_PROBE], cwd=str(site["app"]))
    subprocess.run(script, shell=True, cwd=tmp_path, capture_output=True)
    assert not any(path.name == "pwned" for path in tmp_path.rglob("pwned"))


@pytest.mark.django_db
def test_discovery_needs_the_csrf_token_of_the_session(admin, server, hosts):
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(admin)

    response = client.post(DISCOVER, {"server": str(server.pk)}, format="json")

    assert response.status_code == 403
    assert hosts.sessions == []


@pytest.mark.django_db
def test_an_uploaded_manage_py_is_not_run_without_the_password(
    api, admin, server, site, hosts
):
    uploads = site["home"] / "uploads"
    uploads.mkdir()
    uploads.chmod(0o755)
    application = make_application(
        admin, name="shop", server=server, file_roots=[str(uploads)]
    )
    ApplicationRepository().update(application, last_check_status="ok")
    sent = api.post(
        f"/api/files/{application.pk}/upload/",
        {"path": str(uploads), "file": SimpleUploadedFile("manage.py", b"import os\n")},
        format="multipart",
    )
    assert sent.status_code == 201
    planted_answers(hosts, "python3")

    refused = api.post(
        DISCOVER, {"server": str(server.pk), "folder": str(uploads)}, format="json"
    )

    assert refused.status_code == 400
    assert all("manage.py" not in argv for argv in ran(hosts))
    discovering(api, server, uploads)
    assert any("manage.py" in argv for argv in ran(hosts))


@pytest.mark.django_db
def test_a_virtualenv_whose_parent_others_can_write_is_never_run(
    api, server, site, hosts
):
    open_parent = site["srv"] / "drop"
    open_parent.mkdir()
    planted = venv(open_parent / "env")
    open_parent.chmod(0o777)
    beside = venv(site["srv"] / "beside-env")

    [found] = discovering(api, server, site["app"]).json()["candidates"]

    assert planted not in found["python_paths"]
    assert planted not in {argv[0] for argv in ran(hosts)}
    assert beside in found["python_paths"]


@pytest.mark.django_db
def test_one_search_probes_a_bounded_number_of_pythons(api, server, site, hosts):
    for number in range(12):
        venv(site["app"] / f"env-{number:02}")

    discovering(api, server, site["app"])

    probed = [argv[0] for argv in ran(hosts) if argv[1:] == ["-c", VERSION_PROBE]]
    assert len(probed) == pythons.PROBES_PER_SEARCH
    assert probed[-2:] == ["python3", "python"]
