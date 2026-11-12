"""The connection details a DBS manager needs, shown in the panel and by `manage.py dbs connection`."""

import base64
import hashlib
import json
import sys
import types
from io import StringIO

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client

from dbs import __version__, connection
from dbs.models import AuditEvent

KEYS = {
    "dbs_connection",
    "container",
    "hostname",
    "ssh_user",
    "project_dir",
    "python_path",
    "manage_path",
    "settings_module",
    "remote_backup_dir",
    "file_roots",
    "env_path",
    "dbs_version",
    "host_keys",
}


@pytest.fixture
def on_a_host(monkeypatch):
    monkeypatch.setattr(connection, "in_container", lambda: False)


@pytest.fixture
def in_a_container(monkeypatch):
    monkeypatch.setattr(connection, "in_container", lambda: True)


def test_the_details_name_everything_the_manager_needs(settings, tmp_path, on_a_host):
    settings.DBS_BACKUP_DIR = str(tmp_path)

    info = connection.details()

    assert set(info) == KEYS
    assert info["dbs_connection"] == 2
    assert info["container"] is False
    assert info["dbs_version"] == __version__
    assert info["remote_backup_dir"] == str(tmp_path)
    assert info["settings_module"] == "tests.settings"


@pytest.fixture
def project(tmp_path, monkeypatch):
    folder = tmp_path / "srv" / "shop"
    package = folder / "config"
    package.mkdir(parents=True)
    module = types.ModuleType("shop_config.settings")
    module.__file__ = str(package / "settings.py")
    monkeypatch.setitem(sys.modules, "shop_config.settings", module)
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "shop_config.settings")
    monkeypatch.setattr(connection, "project_dir", lambda: str(folder))
    return folder


def test_a_project_with_no_env_file_names_none(project):
    assert connection.details()["env_path"] == ""


@pytest.mark.parametrize("place", [".", "config", ".."])
def test_the_env_file_is_named_beside_manage_py_beside_the_settings_or_in_the_folder_above(
    project, place
):
    env_file = (project / place).resolve() / ".env"
    env_file.write_text("SECRET_KEY=x\n")

    assert connection.details()["env_path"] == str(env_file)


def test_the_env_file_beside_manage_py_is_named_before_any_other(project):
    for place in (".", "config", ".."):
        (project / place / ".env").write_text("SECRET_KEY=x\n")

    assert connection.details()["env_path"] == str(project / ".env")


def test_the_env_file_beside_the_settings_is_named_before_the_one_above(project):
    for place in ("config", ".."):
        (project / place / ".env").write_text("SECRET_KEY=x\n")

    assert connection.details()["env_path"] == str(project / "config" / ".env")


def test_a_folder_named_env_is_not_an_env_file(project):
    (project / ".env").mkdir()

    assert connection.details()["env_path"] == ""


def test_the_details_never_carry_a_secret(settings):
    settings.DBS_PASSPHRASE = "never-shown-passphrase"

    printed = json.dumps(connection.details())

    assert "never-shown-passphrase" not in printed
    assert settings.SECRET_KEY not in printed


def test_host_key_fingerprints_use_the_openssh_format(tmp_path):
    blob = b"\x00\x00\x00\x0bssh-ed25519" + b"k" * 32
    (tmp_path / "ssh_host_ed25519_key.pub").write_text(
        "ssh-ed25519 " + base64.b64encode(blob).decode() + " root@host\n"
    )

    keys = connection.host_keys(str(tmp_path / "ssh_host_*_key.pub"))

    expected = base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
    assert keys == [{"type": "ssh-ed25519", "fingerprint": "SHA256:" + expected}]


def test_the_command_prints_json():
    out = StringIO()

    call_command("dbs", "connection", "--json", stdout=out)

    assert json.loads(out.getvalue())["dbs_connection"] == 2


@pytest.mark.django_db
def test_inside_a_container_no_container_fact_passes_for_the_servers(in_a_container):
    info = connection.details()

    assert info["container"] is True
    assert info["hostname"] == ""
    assert info["ssh_user"] == ""
    assert info["host_keys"] == []
    assert info["project_dir"]


@pytest.mark.parametrize(
    "cgroup, expected",
    [
        ("0::/system.slice/docker-3f2a.scope\n", True),
        ("0::/machine.slice/libpod-9c1b.scope\n", True),
        ("0::/init.scope\n", False),
    ],
)
def test_the_cgroup_tells_a_container_without_marker_files(tmp_path, cgroup, expected):
    path = tmp_path / "cgroup"
    path.write_text(cgroup)

    assert connection.in_container(markers=(), cgroup=str(path)) is expected


def test_a_marker_file_tells_a_container(tmp_path):
    marker = tmp_path / ".dockerenv"
    marker.write_text("")

    assert connection.in_container(markers=(str(marker),), cgroup=str(tmp_path / "none"))


@pytest.mark.django_db
def test_the_panel_explains_how_to_add_the_project_and_records_nothing(settings, on_a_host):
    settings.DBS_SETUP_WIZARD = False
    client = Client()
    client.force_login(User.objects.create_superuser("root", "root@example.com", "pw"))
    before = AuditEvent.objects.count()

    response = client.get("/admin/dbs/panel/connection/")

    assert response.status_code == 200
    assert b"give it the project" in response.content
    assert b"runs in a container" not in response.content
    assert AuditEvent.objects.count() == before


@pytest.mark.django_db
def test_the_panel_says_when_the_project_runs_in_a_container(settings, in_a_container):
    settings.DBS_SETUP_WIZARD = False
    client = Client()
    client.force_login(User.objects.create_superuser("root", "root@example.com", "pw"))

    response = client.get("/admin/dbs/panel/connection/")

    assert b"This project runs in a container" in response.content
    assert b"<th>Host</th>" not in response.content


@pytest.mark.django_db
def test_the_panel_is_for_superusers_only(settings):
    settings.DBS_SETUP_WIZARD = False
    client = Client()
    client.force_login(User.objects.create_user("staff", "s@example.com", "pw", is_staff=True))

    assert client.get("/admin/dbs/panel/connection/").status_code != 200
