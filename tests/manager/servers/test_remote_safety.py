from __future__ import annotations

import os
import subprocess
import sys

import pytest

import dbs
from dbs.manager.servers.services import browse_service
from dbs.manager.servers.services.pythons import VERSION_PROBE
from tests.manager.remote import scripted_hosts

PLANTED_VERSION = "9.9.9"


def browse(server_id):
    return f"/api/servers/{server_id}/browse/"


@pytest.fixture
def site(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.chdir(home)
    return {"home": home}


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
@pytest.mark.parametrize(
    "path", ["/srv/app\x00/etc", "srv/app", "/srv/../etc", "~/app"]
)
def test_browsing_refuses_a_path_that_is_not_plain_and_absolute(
    api, configured_server, monkeypatch, path
):
    hosts = scripted_hosts(monkeypatch)

    listed = api.get(browse(configured_server.pk), {"path": path})

    assert listed.status_code == 400
    assert hosts.sessions == []


@pytest.mark.django_db
def test_browsing_an_unknown_server_is_not_found(api, monkeypatch):
    scripted_hosts(monkeypatch)

    response = api.get(browse("00000000-0000-0000-0000-000000000000"))

    assert response.status_code == 404


@pytest.mark.django_db
def test_browsing_runs_no_command_on_the_server(
    api, configured_server, site, monkeypatch
):
    (site["home"] / "manage.py").write_text("")
    hosts = scripted_hosts(monkeypatch)

    body = api.get(browse(configured_server.pk), {"path": str(site["home"])}).json()

    assert body["project"] is True
    assert hosts.runs("10.0.0.5") == []


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
