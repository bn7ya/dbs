from __future__ import annotations

import json

import pytest

import dbs
from dbs.manager.applications.repositories import ApplicationRepository
from dbs.manager.applications.services import ApplicationService
from dbs.manager.servers import versions
from dbs.manager.servers.exceptions import (
    HostKeyChanged,
    RemoteCommandFailed,
    RemoteCommandTimedOut,
    ServerConnectionLost,
    SSHAuthFailed,
    SSHUnreachable,
)
from tests.manager.factories import make_application
from tests.manager.servers.support import (
    BACKUP_DIR,
    ENV_PATH,
    MEDIA_ROOT,
    PROJECT_DIR,
    PYTHON,
    REMOTE_DBS_VERSION,
    SETTINGS_MODULE,
    DBS_VERSION,
    FakeRemote,
    Result,
    connecting_to,
    healthy_remote,
    refusing_with,
)
from tests.manager.support import logged

CONNECT = "dbs.manager.servers.services.connection_service.connect"
HEALTH = {
    "status": "warn",
    "checks": [{"name": "backup age", "status": "warn", "message": "2 days old"}],
    "last_backup_at": "2026-10-07T03:00:00Z",
    "generated_at": "2026-10-09T03:00:00Z",
    "schedule": {"enabled": True, "mode": "process", "every": "1d"},
}
HEALTH_ARGV = (PYTHON, "manage.py", "dbs", "health", "--json")


def check(application_id) -> str:
    return f"/api/applications/{application_id}/check/"


def remote_with(version, health=None):
    answers = {
        ("uname", "-sr"): Result(0, "Linux 6.1\n"),
        (PYTHON, "-c", DBS_VERSION): Result(0, f"{version}\n"),
        (PYTHON, "manage.py", "dbs_backup", "--help"): Result(0, "usage\n"),
    }
    if health is not None:
        answers[HEALTH_ARGV] = Result(0, health)
    return FakeRemote(answers=answers, paths={ENV_PATH, MEDIA_ROOT, BACKUP_DIR})


@pytest.mark.django_db
def test_an_application_with_everything_in_place_is_ok(
    api, monkeypatch, application, private_key, host_key
):
    remote = healthy_remote()
    monkeypatch.setattr(CONNECT, connecting_to(remote))

    response = api.post(check(application.pk))

    assert response.status_code == 200
    body = response.json()
    assert body["last_check_status"] == "ok"
    assert body["last_check_error"] == ""
    assert body["last_checked_at"] is not None
    assert body["last_check_report"] == {
        "system": "Linux 6.1.0-18-amd64",
        "dbs_version": REMOTE_DBS_VERSION,
        "dbs_error": "",
        "python_suggestion": None,
        "backup_command": True,
        "env_file": True,
        "roots": {MEDIA_ROOT: True},
        "remote_backup_dir": True,
        "panel_schedule": None,
    }
    assert remote.credentials.private_key == private_key
    assert remote.credentials.host_key == host_key
    assert (remote.credentials.host, remote.credentials.port) == ("10.0.0.5", 2222)


@pytest.mark.django_db
def test_the_check_runs_argv_lists_in_the_project(api, monkeypatch, application):
    remote = healthy_remote()
    monkeypatch.setattr(CONNECT, connecting_to(remote))

    api.post(check(application.pk))

    settings = {"DJANGO_SETTINGS_MODULE": SETTINGS_MODULE}
    assert remote.runs == [
        {"argv": [PYTHON, "-c", DBS_VERSION], "cwd": PROJECT_DIR, "env": None},
        {
            "argv": [PYTHON, "manage.py", "dbs_backup", "--help"],
            "cwd": PROJECT_DIR,
            "env": settings,
        },
        {"argv": ["uname", "-sr"], "cwd": None, "env": None},
        {"argv": list(HEALTH_ARGV), "cwd": PROJECT_DIR, "env": settings},
    ]


@pytest.mark.django_db
def test_something_configured_but_missing_is_a_problem(api, monkeypatch, application):
    remote = healthy_remote()
    remote.paths -= {ENV_PATH, MEDIA_ROOT}
    remote.answers = {
        **remote.answers,
        (PYTHON, "-c", DBS_VERSION): Result(127, "", f"sh: 1: {PYTHON}: not found"),
    }
    monkeypatch.setattr(CONNECT, connecting_to(remote))

    body = api.post(check(application.pk)).json()

    assert body["last_check_status"] == "problem"
    report = body["last_check_report"]
    assert report["dbs_version"] is None
    assert report["env_file"] is False
    assert report["roots"] == {MEDIA_ROOT: False}
    assert report["backup_command"] is True


@pytest.mark.django_db
def test_a_probe_that_fails_marks_only_its_own_item(api, monkeypatch, application):
    remote = FakeRemote(
        answers={
            ("uname", "-sr"): Result(0, "\n"),
            (PYTHON, "-c", DBS_VERSION): Result(
                1, "", "ModuleNotFoundError: No module named 'dbs'"
            ),
            (PYTHON, "manage.py", "dbs_backup", "--help"): Result(
                1, "", "Unknown command: 'dbs_backup'"
            ),
        },
        paths={ENV_PATH, MEDIA_ROOT},
        unreadable=frozenset({BACKUP_DIR}),
    )
    monkeypatch.setattr(CONNECT, connecting_to(remote))

    body = api.post(check(application.pk)).json()

    assert body["last_check_status"] == "problem"
    assert body["last_check_report"] == {
        "system": None,
        "dbs_version": None,
        "dbs_error": "ModuleNotFoundError: No module named 'dbs'",
        "python_suggestion": None,
        "backup_command": False,
        "env_file": True,
        "roots": {MEDIA_ROOT: True},
        "remote_backup_dir": False,
        "panel_schedule": None,
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("probe", "error", "code"),
    [
        (
            (PYTHON, "manage.py", "dbs_backup", "--help"),
            RemoteCommandFailed(),
            "remote_command_failed",
        ),
        ((PYTHON, "-c", DBS_VERSION), ServerConnectionLost(), "connection_lost"),
        (HEALTH_ARGV, RemoteCommandTimedOut(), "remote_command_timed_out"),
    ],
)
def test_a_probe_that_cannot_run_fails_the_check_instead_of_reporting_a_problem(
    api, monkeypatch, application, probe, error, code
):
    remote = remote_with(REMOTE_DBS_VERSION, json.dumps(HEALTH))
    monkeypatch.setattr(CONNECT, connecting_to(remote))
    api.post(check(application.pk))
    remote.answers = {**remote.answers, probe: error}

    response = api.post(check(application.pk))

    assert response.json()["error"]["code"] == code
    stored = ApplicationRepository().get(application.pk)
    assert (stored.last_check_status, stored.last_check_error) == ("failed", code)
    assert stored.last_check_report == {}
    assert stored.last_health == HEALTH


@pytest.mark.django_db
def test_a_missing_django_dbs_names_the_python_that_has_it(
    api, monkeypatch, application
):
    remote = healthy_remote()
    remote.paths |= {f"{PROJECT_DIR}/venv/bin/python"}
    remote.answers = {
        **remote.answers,
        (PYTHON, "-c", DBS_VERSION): Result(127, "", f"sh: 1: {PYTHON}: not found"),
        (f"{PROJECT_DIR}/venv/bin/python", "-c", DBS_VERSION): Result(0, "0.8.0\n"),
    }
    monkeypatch.setattr(CONNECT, connecting_to(remote))

    body = api.post(check(application.pk)).json()

    report = body["last_check_report"]
    assert (body["remote_version"], body["installed"]) == (None, False)
    assert report["dbs_error"] == f"sh: 1: {PYTHON}: not found"
    assert report["python_suggestion"] == {
        "python_path": f"{PROJECT_DIR}/venv/bin/python",
        "dbs_version": "0.8.0",
    }
    assert ApplicationRepository().get(application.pk).python_path == PYTHON


@pytest.mark.django_db
def test_what_is_not_configured_is_not_looked_at(api, admin, monkeypatch, server):
    bare = make_application(admin, name="bare", server=server)
    remote = healthy_remote()
    remote.answers = {
        ("uname", "-sr"): remote.answers[("uname", "-sr")],
        ("python3", "-c", DBS_VERSION): remote.answers[(PYTHON, "-c", DBS_VERSION)],
    }
    monkeypatch.setattr(CONNECT, connecting_to(remote))

    body = api.post(check(bare.pk)).json()

    assert body["last_check_status"] == "ok"
    assert body["last_check_report"] == {
        "system": "Linux 6.1.0-18-amd64",
        "dbs_version": REMOTE_DBS_VERSION,
        "dbs_error": "",
        "python_suggestion": None,
        "backup_command": None,
        "env_file": None,
        "roots": {},
        "remote_backup_dir": True,
        "panel_schedule": None,
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (HostKeyChanged(), 409, "host_key_changed"),
        (SSHAuthFailed(), 400, "ssh_auth_failed"),
        (SSHUnreachable(), 502, "ssh_unreachable"),
    ],
)
def test_a_connection_that_fails_is_stored_on_the_application_and_reported(
    api, monkeypatch, application, error, status, code
):
    monkeypatch.setattr(CONNECT, refusing_with(error))

    response = api.post(check(application.pk))

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    stored = api.get(f"/api/applications/{application.pk}/").json()
    assert stored["last_check_status"] == "failed"
    assert stored["last_check_error"] == code
    assert stored["last_checked_at"] is not None
    assert stored["last_check_report"] == {}
    [entry] = logged("application.check")
    assert (entry.status, entry.error_code, entry.data) == (
        "failed",
        code,
        {"status": "failed"},
    )


@pytest.mark.django_db
def test_a_check_is_logged_against_the_application(api, monkeypatch, application):
    monkeypatch.setattr(CONNECT, connecting_to(healthy_remote()))

    api.post(check(application.pk))

    [entry] = logged("application.check")
    assert (entry.status, entry.subject, entry.data) == (
        "succeeded",
        str(application.pk),
        {"status": "ok"},
    )


@pytest.mark.django_db
def test_a_check_compares_versions_and_reads_health(api, monkeypatch, application):
    remote = remote_with("0.8.1", json.dumps(HEALTH))
    monkeypatch.setattr(CONNECT, connecting_to(remote))

    body = api.post(check(application.pk)).json()

    assert body["local_version"] == dbs.__version__
    assert (body["remote_version"], body["compatible"]) == ("0.8.1", True)
    assert body["last_health"] == HEALTH
    assert body["last_check_report"]["panel_schedule"] == {
        "enabled": True,
        "mode": "process",
    }
    assert body["last_check_status"] == "ok"
    assert ApplicationRepository().get(application.pk).last_health == HEALTH


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("version", "compatible"),
    [
        (versions.MINIMUM_REMOTE, True),
        ("0.7.3", True),
        ("0.6.9", False),
        ("0.5.0", False),
    ],
)
def test_a_remote_is_compatible_from_the_minimum_version_and_health_always_runs(
    api, monkeypatch, application, version, compatible
):
    remote = remote_with(version, json.dumps(HEALTH))
    monkeypatch.setattr(CONNECT, connecting_to(remote))

    body = api.post(check(application.pk)).json()

    assert (body["remote_version"], body["compatible"]) == (version, compatible)
    assert body["installed"] is True
    assert body["last_health"] == HEALTH
    assert list(HEALTH_ARGV) in [run["argv"] for run in remote.runs]


@pytest.mark.django_db
def test_without_django_dbs_health_is_not_asked(api, monkeypatch, application):
    remote = remote_with("ignored")
    remote.answers = {
        **remote.answers,
        (PYTHON, "-c", DBS_VERSION): Result(1, "", "No module named 'dbs'"),
    }
    monkeypatch.setattr(CONNECT, connecting_to(remote))

    body = api.post(check(application.pk)).json()

    assert body["last_health"] is None
    assert list(HEALTH_ARGV) not in [run["argv"] for run in remote.runs]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "health", ["not json", "[]", json.dumps({"status": "great", "checks": []})]
)
def test_health_that_is_not_the_documented_json_is_ignored(
    api, monkeypatch, application, health
):
    monkeypatch.setattr(CONNECT, connecting_to(remote_with("0.8.0", health)))

    body = api.post(check(application.pk)).json()

    assert body["last_health"] is None
    assert body["last_check_report"]["panel_schedule"] is None


@pytest.mark.django_db
def test_checked_through_the_service_carries_the_compatibility(
    admin, monkeypatch, application
):
    monkeypatch.setattr(CONNECT, connecting_to(remote_with("0.6.0")))

    checked = ApplicationService(admin).checked(application.pk)

    assert checked.application.pk == application.pk
    assert checked.compatibility == {
        "local_version": dbs.__version__,
        "remote_version": "0.6.0",
        "installed": True,
        "compatible": False,
    }
