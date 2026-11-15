import pytest
from rest_framework.test import APIClient

import dbs
from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.applications.repositories import ApplicationRepository
from dbs.manager.backups.models import BackupFile
from dbs.manager.backups.repositories import BackupFileRepository
from dbs.manager.permissions import Capability, Role, capabilities
from dbs.manager.redeploy import updating
from dbs.manager.redeploy.catalogue import Place
from tests.manager.factories import make_application
from tests.manager.servers.support import DBS_VERSION, PASSWORD
from tests.manager.support import logged
from tests.manager.test_redeploy import PYTHON, TARGET, job_of, statuses

WANTED = dbs.__version__
SELF_UPDATE = [PYTHON, "manage.py", "dbs", "upgrade", "--self", "--to", WANTED, "--yes"]
PIP_INSTALL = [PYTHON, "-m", "pip", "install", "--no-input", f"django-dbs=={WANTED}"]
PIP_VERSION = [PYTHON, "-m", "pip", "--version"]
UPGRADE = [PYTHON, "manage.py", "dbs", "upgrade"]
RESTART = ["systemctl", "--user", "restart", "shop.service"]
ALL_STEPS = ["check", "safety_backup", "install", "upgrade", "restart", "final_check"]


def update_url(application):
    return f"/api/applications/{application.pk}/update-dbs/"


@pytest.fixture
def updatable(world):
    return ready_to_update(world, installed="0.8.1")


def ready_to_update(world, *, installed, install=None, applies=True):
    hosts, events = world["hosts"], world["sent"]["events"]
    running = [installed]

    def version(argv, stdin_line):
        return 0, f"{running[-1]}\n", ""

    def installing(argv, stdin_line):
        events.append("install")
        if applies:
            running.append(argv[argv.index("--to") + 1] if "--to" in argv else WANTED)
        return 0, f"installed django-dbs {WANTED}\n", ""

    def upgrading(argv, stdin_line):
        events.append("upgrade")
        return 0, "[done] migrations\n", ""

    def restarting(argv, stdin_line):
        events.append("restart")
        return 0, "", ""

    hosts.answer(TARGET, [PYTHON, "-c", DBS_VERSION], version)
    hosts.answer(TARGET, install or SELF_UPDATE, installing)
    hosts.answer(TARGET, PIP_VERSION, (0, "pip 25.0 from /srv/app/.venv\n", ""))
    hosts.answer(TARGET, UPGRADE, upgrading)
    hosts.answer(TARGET, RESTART, restarting)
    return world


def updated(api, world, run_jobs, **fields):
    body = {
        "rehearsal": False,
        "password": PASSWORD,
        "confirm_name": world["target"].name,
        **fields,
    }
    with run_jobs():
        response = api.post(update_url(world["target"]), body, format="json")
    return job_of(api, response)


def ran(world, argv):
    return [
        run
        for session in world["hosts"].sessions
        for run in session.runs
        if run["argv"][: len(argv)] == argv
    ]


def with_restart_step(world):
    ApplicationRepository().update(
        world["target"],
        deploy_steps=[
            {"kind": "migrate", "options": {}, "timeout_minutes": 10},
            {
                "kind": "systemd_user_restart",
                "options": {"unit": "shop.service"},
                "timeout_minutes": 5,
            },
        ],
    )


@pytest.mark.django_db
def test_an_update_backs_up_installs_finishes_restarts_and_checks(api, updatable, run_jobs):
    with_restart_step(updatable)

    job = updated(api, updatable, run_jobs)

    assert job["status"] == "succeeded", job
    assert job["action"] == "application.dbs_update"
    assert statuses(job) == [(step, "succeeded") for step in ALL_STEPS]
    assert updatable["sent"]["events"] == [f"backup {TARGET}", "install", "upgrade", "restart"]
    detail = job["detail"]
    assert (detail["from_version"], detail["version"], detail["to_version"]) == (
        "0.8.1",
        WANTED,
        WANTED,
    )
    safety = BackupFileRepository().get(detail["safety_backup"])
    assert (safety.application_id, safety.kind) == (updatable["target"].pk, BackupFile.Kind.DBS)
    assert "restart_needed" not in detail
    assert len(ran(updatable, SELF_UPDATE)) == 1 and ran(updatable, PIP_INSTALL) == []
    assert ran(updatable, ["dbs_backup"]) == []


@pytest.mark.django_db
def test_every_step_of_an_update_is_audited_against_the_application(api, updatable, run_jobs):
    updated(api, updatable, run_jobs)

    for step in ALL_STEPS:
        [entry] = logged(f"dbs_update.{step}")
        assert entry.subject == str(updatable["target"].pk)


@pytest.mark.django_db
def test_an_application_without_a_restart_step_is_said_to_need_a_restart(
    api, updatable, run_jobs
):
    job = updated(api, updatable, run_jobs)

    assert job["status"] == "succeeded", job
    assert dict(statuses(job))["restart"] == "skipped"
    assert job["detail"]["restart_needed"] is True
    assert "restart" not in updatable["sent"]["events"]


@pytest.mark.django_db
def test_an_application_before_it_could_update_itself_is_updated_with_pip(
    api, world, run_jobs
):
    ready_to_update(world, installed="0.7.4", install=PIP_INSTALL)

    job = updated(api, world, run_jobs)

    assert job["status"] == "succeeded", job
    [installed] = ran(world, PIP_INSTALL)
    assert installed["argv"] == PIP_INSTALL
    assert ran(world, SELF_UPDATE) == []


@pytest.mark.django_db
def test_a_release_can_be_named(api, world, run_jobs):
    named = [PYTHON, "manage.py", "dbs", "upgrade", "--self", "--to", "0.8.2", "--yes"]
    ready_to_update(world, installed="0.8.1", install=named)

    job = updated(api, world, run_jobs, to="0.8.2")

    assert job["status"] == "succeeded", job
    assert (job["detail"]["version"], job["detail"]["to_version"]) == ("0.8.2", "0.8.2")


@pytest.mark.django_db
@pytest.mark.parametrize("to", ["latest", "0.9", "0.9.0; rm -rf /", "-r requirements.txt", "9"])
def test_a_release_is_three_numbers_and_nothing_else(api, updatable, to):
    response = api.post(update_url(updatable["target"]), {"to": to}, format="json")

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"to": ["invalid_version"]}


@pytest.mark.django_db
def test_a_rehearsal_checks_and_changes_nothing(api, updatable, run_jobs):
    with run_jobs():
        response = api.post(update_url(updatable["target"]), {}, format="json")
    job = job_of(api, response)

    assert job["status"] == "succeeded", job
    assert statuses(job) == [
        ("check", "succeeded"),
        ("safety_backup", "succeeded"),
        ("install", "succeeded"),
        ("upgrade", "skipped"),
        ("restart", "skipped"),
        ("final_check", "skipped"),
    ]
    assert updatable["sent"]["events"] == []
    assert updatable["sent"]["taken"] == []
    assert len(ran(updatable, PIP_VERSION)) == 1
    assert ran(updatable, SELF_UPDATE) == [] and ran(updatable, UPGRADE) == []


@pytest.mark.django_db
def test_an_application_that_already_runs_the_release_is_left_alone(api, world, run_jobs):
    ready_to_update(world, installed=WANTED)

    job = updated(api, world, run_jobs)

    assert job["status"] == "succeeded", job
    assert job["detail"]["already_current"] is True
    assert statuses(job) == [("check", "succeeded")] + [
        (step, "skipped") for step in ALL_STEPS[1:]
    ]
    assert world["sent"]["events"] == []


@pytest.mark.django_db
def test_an_application_that_runs_a_newer_release_is_not_taken_back(api, world, run_jobs):
    ready_to_update(world, installed="9.9.9")

    job = updated(api, world, run_jobs)

    assert (job["status"], job["error_code"]) == ("failed", "update_would_downgrade")
    assert job["detail"]["failed_step"] == "check"
    assert world["sent"]["events"] == []
    assert "revertable" not in job["detail"] or job["detail"]["revertable"] is False


@pytest.mark.django_db
def test_an_install_that_changed_nothing_fails_the_update_and_offers_the_safety_backup(
    api, world, run_jobs
):
    ready_to_update(world, installed="0.8.1", applies=False)

    job = updated(api, world, run_jobs)

    assert (job["status"], job["error_code"]) == ("failed", "update_not_applied")
    assert job["detail"]["failed_step"] == "final_check"
    assert job["detail"]["revertable"] is True
    assert job["detail"]["to_version"] == "0.8.1"


@pytest.mark.django_db
def test_an_install_that_fails_stops_the_update_with_its_output(api, updatable, run_jobs):
    updatable["hosts"].answer(
        TARGET, SELF_UPDATE, (1, "", "CommandError: pip failed: no matching distribution\n")
    )

    job = updated(api, updatable, run_jobs)

    assert (job["status"], job["error_code"]) == ("failed", "remote_command_failed")
    assert job["detail"]["failed_step"] == "install"
    assert "no matching distribution" in job["detail"]["output"]
    assert dict(statuses(job))["upgrade"] == "skipped"
    assert "upgrade" not in updatable["sent"]["events"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("fields", "code"),
    [
        ({"password": ""}, "invalid"),
        ({"confirm_name": "web-1"}, "confirm_name_mismatch"),
        ({"password": "not-the-password"}, "invalid_password"),
    ],
)
def test_a_real_update_needs_the_name_and_the_password(api, updatable, fields, code):
    body = {"rehearsal": False, "password": PASSWORD, "confirm_name": "web-2", **fields}

    response = api.post(update_url(updatable["target"]), body, format="json")

    assert response.status_code in (400, 403)
    assert response.json()["error"]["code"] == code
    assert updatable["sent"]["events"] == []


@pytest.mark.django_db
def test_an_application_in_a_container_is_told_to_build_its_image_again(api, admin, updatable):
    contained = make_application(
        admin,
        "web-3",
        TARGET,
        kind="compose",
        engine="docker",
        compose_project="shop",
        compose_service="web",
        project_dir="/srv/shop",
        backup_passphrase="a-passphrase-for-the-container",
    )

    response = api.post(update_url(contained), {}, format="json")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "update_needs_rebuild"


@pytest.mark.django_db
def test_an_operator_may_rehearse_an_update_but_not_run_one(updatable, run_jobs):
    operator = UserRepository().create(username="omar", password=PASSWORD, role=Role.OPERATOR)
    viewer = UserRepository().create(username="vera", password=PASSWORD, role=Role.VIEWER)
    client, watching = APIClient(), APIClient()
    client.force_login(operator)
    watching.force_login(viewer)
    target = updatable["target"]

    with run_jobs():
        rehearsed = client.post(update_url(target), {}, format="json")
    real = client.post(
        update_url(target),
        {"rehearsal": False, "password": PASSWORD, "confirm_name": "web-2"},
        format="json",
    )
    watched = watching.post(update_url(target), {}, format="json")

    assert rehearsed.status_code == 202
    assert (real.status_code, real.json()["error"]["code"]) == (403, "role_required")
    assert watched.status_code == 403
    assert Capability.APPLICATIONS_UPDATE in capabilities(Role.ADMIN)
    assert Capability.APPLICATIONS_UPDATE not in capabilities(Role.OPERATOR)


def test_what_an_update_runs_is_a_fixed_list_of_arguments():
    place = Place("host", "/srv/app", PYTHON, None, "", "", "")

    recent = updating.install_command(place, "0.8.0", "0.9.0")
    older = updating.install_command(place, "0.7.9", "0.9.0")
    unknown = updating.install_command(place, None, "0.9.0")

    assert (recent.argv, recent.manage) == (
        ["dbs", "upgrade", "--self", "--to", "0.9.0", "--yes"],
        True,
    )
    assert older.argv == [PYTHON, "-m", "pip", "install", "--no-input", "django-dbs==0.9.0"]
    assert (older.cwd, older.manage) == ("/srv/app", False)
    assert unknown.argv == older.argv
    assert updating.upgrade_command().argv == ["dbs", "upgrade"]
    assert updating.target_version("") == dbs.__version__


def test_only_restart_steps_are_run_after_an_update():
    application = type("Application", (), {})()
    application.deploy_steps = [
        {"kind": "git_pull"},
        {"kind": "migrate"},
        {"kind": "systemd_user_restart", "options": {"unit": "shop.service"}},
        {"kind": "pip_install", "options": {"requirements": "requirements.txt"}},
    ]

    assert [step["kind"] for step in updating.restart_steps(application)] == [
        "systemd_user_restart"
    ]
