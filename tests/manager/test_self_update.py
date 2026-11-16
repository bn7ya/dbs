from __future__ import annotations

import signal
import sys
import threading
from argparse import Namespace

import pytest
from rest_framework.test import APIClient

import dbs
from dbs import upgrade
from dbs.manager import cli, selfupdate
from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.activity.services import ActivityService
from dbs.manager.dashboard.services import ManagerUpdateService
from dbs.manager.permissions import Capability, Role, capabilities
from tests.manager.servers.support import PASSWORD
from tests.manager.support import logged

UPDATE = "/api/about/update/"
NEWER = "99.0.0"


@pytest.fixture
def installable(monkeypatch):
    monkeypatch.setattr(upgrade, "is_editable_install", lambda: False)
    monkeypatch.setattr(upgrade, "is_system_interpreter", lambda *args: False)
    monkeypatch.setattr(upgrade, "latest_release", lambda timeout=10.0: NEWER)
    installed = []

    def run(command, **options):
        installed.append(command)
        return Namespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(selfupdate.subprocess, "run", run)
    return installed


@pytest.fixture
def restartable(monkeypatch):
    killed = []
    monkeypatch.setattr(selfupdate.os, "kill", lambda pid, number: killed.append((pid, number)))
    monkeypatch.setattr(selfupdate, "RESTART_AFTER_SECONDS", 0.0)
    selfupdate.RESTART.arm(["run", "--no-browser", "--port", "8765"])
    yield killed
    selfupdate.RESTART.disarm()


@pytest.fixture
def master(db):
    user = UserRepository().create(username="mona", password=PASSWORD, role=Role.MASTER)
    client = APIClient()
    client.force_login(user)
    return client


def run_update(*arguments):
    return cli.main(["update", *arguments])


def test_the_plan_names_one_pinned_release(installable):
    planned = selfupdate.plan()

    assert (planned.current, planned.target) == (dbs.__version__, NEWER)
    assert planned.command == [sys.executable, "-m", "pip", "install", f"django-dbs=={NEWER}"]
    assert planned.needed


def test_the_installed_release_needs_nothing(installable):
    planned = selfupdate.plan(dbs.__version__)

    assert not planned.needed and planned.command == []


@pytest.mark.parametrize(
    ("to", "code"),
    [("0.0.1", selfupdate.DOWNGRADE), ("latest", selfupdate.INVALID_VERSION), ("9;rm", selfupdate.INVALID_VERSION)],
)
def test_an_older_release_and_a_name_that_is_no_release_are_refused(installable, to, code):
    with pytest.raises(selfupdate.Refused) as refused:
        selfupdate.plan(to)

    assert refused.value.code == code


def test_a_source_checkout_and_a_python_shared_with_the_system_are_refused(
    installable, monkeypatch
):
    monkeypatch.setattr(upgrade, "is_system_interpreter", lambda *args: True)
    with pytest.raises(selfupdate.Refused) as shared:
        selfupdate.plan()
    allowed = selfupdate.plan(system_python=True)
    monkeypatch.setattr(upgrade, "is_editable_install", lambda: True)
    with pytest.raises(selfupdate.Refused) as checkout:
        selfupdate.plan(system_python=True)

    assert shared.value.code == selfupdate.SYSTEM_PYTHON
    assert allowed.needed
    assert checkout.value.code == selfupdate.SOURCE_CHECKOUT


def test_an_unreachable_index_asks_for_a_release_by_name(installable, monkeypatch):
    monkeypatch.setattr(upgrade, "latest_release", lambda timeout=10.0: None)

    with pytest.raises(selfupdate.Refused) as refused:
        selfupdate.plan()
    with pytest.raises(selfupdate.Refused) as offline:
        selfupdate.plan(offline=True)

    assert refused.value.code == offline.value.code == selfupdate.UNREACHABLE
    assert selfupdate.plan(NEWER, offline=True).target == NEWER


def test_a_failed_install_says_what_pip_said(installable, monkeypatch):
    monkeypatch.setattr(
        selfupdate.subprocess,
        "run",
        lambda command, **options: Namespace(
            returncode=1, stdout="", stderr="Collecting\nERROR: No matching distribution\n"
        ),
    )

    with pytest.raises(selfupdate.Refused) as refused:
        selfupdate.install(selfupdate.plan())

    assert refused.value.code == selfupdate.FAILED
    assert "No matching distribution" in str(refused.value)


def test_the_restart_runs_the_manager_again_on_the_same_port_and_folder():
    args = Namespace(
        host="127.0.0.1",
        trusted_proxy=["10.0.0.0/24"],
        allow_insecure_http=False,
        terminal="master",
        database_url=None,
    )

    arguments = selfupdate.run_arguments(args, 8799, "/srv/manager")

    assert arguments == [
        "run", "--no-browser", "--host", "127.0.0.1", "--port", "8799",
        "--data-dir", "/srv/manager", "--trusted-proxy", "10.0.0.0/24",
        "--terminal", "master",
    ]


def test_a_restart_is_followed_only_once_it_was_asked_for(monkeypatch, restartable):
    executed = []
    monkeypatch.setattr(selfupdate.os, "execv", lambda path, argv: executed.append((path, argv)))

    selfupdate.RESTART.follow()
    assert executed == []

    assert selfupdate.RESTART.request() is True
    selfupdate.RESTART.follow()

    assert executed == [
        (sys.executable, [sys.executable, "-m", "dbs.manager", "run", "--no-browser", "--port", "8765"])
    ]


def test_asking_for_a_restart_signals_this_process_to_stop(restartable):
    selfupdate.RESTART.request()
    for thread in threading.enumerate():
        if isinstance(thread, threading.Timer):
            thread.join(2)

    assert restartable and restartable[0][1] == signal.SIGTERM


def test_a_manager_not_started_by_run_cannot_restart_itself():
    selfupdate.RESTART.disarm()

    assert selfupdate.RESTART.armed is False
    assert selfupdate.RESTART.request() is False


def test_update_check_says_what_is_installed_and_what_is_newest(installable, capsys):
    assert run_update("--check") == 0

    said = capsys.readouterr().out
    assert f"django-dbs {dbs.__version__} is installed." in said
    assert f"django-dbs {NEWER} is the newest." in said
    assert installable == []


def test_update_installs_the_newest_release_when_told_yes(installable, capsys, tmp_path):
    assert run_update("--yes", "--data-dir", str(tmp_path)) == 0

    said = capsys.readouterr().out
    assert installable == [[sys.executable, "-m", "pip", "install", f"django-dbs=={NEWER}"]]
    assert f"django-dbs {NEWER} replaces {dbs.__version__} with:" in said
    assert f"Installed django-dbs {NEWER}." in said


def test_update_installs_nothing_without_an_answer(installable, capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    assert run_update("--data-dir", str(tmp_path)) == 1

    assert installable == []
    assert "nothing was installed" in capsys.readouterr().err


def test_update_takes_a_named_release_without_asking_the_index(installable, capsys, tmp_path):
    assert run_update("--to", "98.1.0", "--offline", "--yes", "--data-dir", str(tmp_path)) == 0

    assert installable[0][-1] == "django-dbs==98.1.0"


def test_update_refuses_while_the_manager_runs(installable, capsys, tmp_path, monkeypatch):
    (tmp_path / "instance.json").write_text('{"pid": 424242, "url": "http://127.0.0.1:8765/"}')
    monkeypatch.setattr(cli.paths, "instance_path", lambda folder: tmp_path / "instance.json")
    monkeypatch.setattr(cli, "pid_running", lambda pid: True)

    assert run_update("--yes", "--data-dir", str(tmp_path)) == 1

    assert installable == []
    assert "the manager is running (process 424242)" in capsys.readouterr().err


def test_update_says_why_a_checkout_is_not_updated(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(upgrade, "latest_release", lambda timeout=10.0: NEWER)
    monkeypatch.setattr(upgrade, "is_editable_install", lambda: True)

    assert run_update("--yes", "--data-dir", str(tmp_path)) == 1

    assert "source checkout" in capsys.readouterr().err


@pytest.mark.django_db
def test_only_the_master_may_look_for_an_update_or_install_one(installable, restartable):
    admin = UserRepository().create(username="amal", password=PASSWORD, role=Role.ADMIN)
    client = APIClient()
    client.force_login(admin)

    looked = client.get(UPDATE)
    installed = client.post(UPDATE, {"password": PASSWORD}, format="json")

    assert (looked.status_code, installed.status_code) == (403, 403)
    assert looked.json()["error"]["code"] == "role_required"
    assert capabilities(Role.MASTER)[-1:] and Capability.MANAGER_UPDATE in capabilities(Role.MASTER)
    assert Capability.MANAGER_UPDATE not in capabilities(Role.ADMIN)
    assert installable == []


@pytest.mark.django_db
def test_the_master_sees_what_is_installed_and_what_is_newest(master, installable, restartable):
    found = master.get(UPDATE)

    assert found.status_code == 200
    assert found.json() == {
        "current": dbs.__version__,
        "latest": NEWER,
        "newer": True,
        "refusal": None,
        "busy": False,
    }


@pytest.mark.django_db
def test_the_master_installs_the_release_with_the_password_and_the_manager_restarts(
    master, installable, restartable
):
    done = master.post(UPDATE, {"password": PASSWORD}, format="json")

    assert done.status_code == 200, done.json()
    assert done.json() == {"version": NEWER, "updated": True, "restarting": True}
    assert installable == [[sys.executable, "-m", "pip", "install", f"django-dbs=={NEWER}"]]
    assert selfupdate.RESTART.requested.is_set()
    [entry] = logged("manager.update")
    assert (entry.status, entry.target_name) == ("succeeded", NEWER)
    assert entry.data == {"from": dbs.__version__, "to": NEWER}


@pytest.mark.django_db
def test_a_wrong_password_installs_nothing(master, installable, restartable):
    refused = master.post(UPDATE, {"password": "not-the-password"}, format="json")

    assert refused.json()["error"]["code"] == "invalid_password"
    assert installable == [] and not selfupdate.RESTART.requested.is_set()


@pytest.mark.django_db
def test_the_installed_release_is_left_alone(master, installable, restartable):
    done = master.post(UPDATE, {"password": PASSWORD, "to": dbs.__version__}, format="json")

    assert done.json() == {"version": dbs.__version__, "updated": False, "restarting": False}
    assert installable == [] and logged("manager.update") == []


@pytest.mark.django_db
def test_a_manager_that_cannot_restart_itself_is_updated_from_a_terminal(master, installable):
    selfupdate.RESTART.disarm()

    refused = master.post(UPDATE, {"password": PASSWORD}, format="json")

    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "update_from_terminal")
    assert master.get(UPDATE).json()["refusal"] == "update_from_terminal"
    assert installable == []


@pytest.mark.django_db
def test_an_update_waits_for_running_jobs(master, admin, installable, restartable):
    ActivityService(admin).queue("backup.take", target="web-1")

    refused = master.post(UPDATE, {"password": PASSWORD}, format="json")

    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "update_busy")
    assert master.get(UPDATE).json()["busy"] is True
    assert installable == []


@pytest.mark.django_db
def test_a_refusal_and_a_failed_install_come_back_with_their_code(
    master, installable, restartable, monkeypatch
):
    older = master.post(UPDATE, {"password": PASSWORD, "to": "0.0.1"}, format="json")
    monkeypatch.setattr(
        selfupdate.subprocess,
        "run",
        lambda command, **options: Namespace(returncode=1, stdout="", stderr="ERROR: no\n"),
    )
    failed = master.post(UPDATE, {"password": PASSWORD}, format="json")

    assert older.json()["error"]["code"] == "update_would_downgrade"
    assert (failed.status_code, failed.json()["error"]["code"]) == (409, "update_failed")
    [entry] = logged("manager.update")
    assert (entry.status, entry.error_code) == ("failed", "update_failed")
    assert not selfupdate.RESTART.requested.is_set()


def test_mcp_and_the_console_offer_no_way_to_update_the_manager():
    from dbs.manager.mcp import tools
    from dbs.manager.terminal import parsers

    source = open(tools.__file__, encoding="utf-8").read()
    console = parsers.__file__

    assert "selfupdate" not in source and "manager.update" not in source
    assert "command_update" not in open(console, encoding="utf-8").read()
    assert isinstance(ManagerUpdateService(None), ManagerUpdateService)
