import pytest
from rest_framework.test import APIClient

from dbs import audit
from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.applications.repositories import ApplicationRepository
from dbs.manager.backups.models import BackupFile
from dbs.manager.backups.repositories import BackupFileRepository
from dbs.manager.permissions import Role
from dbs.models import AuditEvent
from tests.manager.servers.support import PASSWORD
from tests.manager.support import logged
from tests.manager.test_redeploy import MIGRATE, PYTHON, TARGET, job_of, statuses

BEFORE = "1f0c2a9d3b4e5f60718293a4b5c6d7e8f9012345"
AFTER = "9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a291807"
STEPS = [
    {"kind": "git_pull", "options": {"remote": "origin", "branch": "main"}},
    {"kind": "migrate", "timeout_minutes": 30},
    {"kind": "systemd_user_restart", "options": {"unit": "shop.service"}},
]


def deploy_url(application):
    return f"/api/applications/{application.pk}/deploy/"


def steps_url(application):
    return f"/api/applications/{application.pk}/deploy-steps/"


@pytest.fixture
def deployable(world):
    return ready_to_deploy(world)


def ready_to_deploy(world):
    target = world["target"]
    project = target.project_dir
    hosts = world["hosts"]
    heads = [BEFORE]

    def head(argv, stdin_line):
        return 0, f"{heads[-1]}\n", ""

    def pull(argv, stdin_line):
        world["sent"]["events"].append("git pull")
        heads.append(AFTER)
        return 0, "Fast-forward\n", ""

    def restart(argv, stdin_line):
        world["sent"]["events"].append("restart")
        return 0, "", ""

    hosts.answer(TARGET, ["git", "-C", project, "rev-parse", "HEAD"], head)
    hosts.answer(
        TARGET,
        ["git", "-C", project, "pull", "--ff-only", "--no-rebase", "origin", "main"],
        pull,
    )
    hosts.answer(TARGET, ["git", "-C", project, "fetch", "--dry-run", "origin"], (0, "", ""))
    hosts.answer(TARGET, ["git", "-C", project, "status", "--porcelain"], (0, "", ""))
    hosts.answer(TARGET, [PYTHON, "manage.py", "migrate", "--plan"], (0, "Planned\n", ""))
    hosts.answer(TARGET, [PYTHON, "manage.py", "check"], (0, "", ""))
    hosts.answer(TARGET, ["systemctl", "--user", "restart", "shop.service"], restart)
    ApplicationRepository().update(target, deploy_steps=STEPS)
    return world


def deployed(api, world, run_jobs, **fields):
    body = {
        "rehearsal": False,
        "password": PASSWORD,
        "confirm_name": world["target"].name,
        **fields,
    }
    with run_jobs():
        response = api.post(deploy_url(world["target"]), body, format="json")
    return job_of(api, response)


def ran(world, argv):
    return [
        run
        for session in world["hosts"].sessions
        for run in session.runs
        if run["argv"][: len(argv)] == argv
    ]


@pytest.mark.django_db
def test_a_rehearsal_reads_every_step_and_changes_nothing(api, deployable, run_jobs):
    with run_jobs():
        response = api.post(deploy_url(deployable["target"]), {}, format="json")
    job = job_of(api, response)

    assert job["status"] == "succeeded", job
    assert statuses(job) == [
        ("check", "succeeded"),
        ("safety_backup", "succeeded"),
        ("record_env", "skipped"),
        ("git_pull", "succeeded"),
        ("migrate", "succeeded"),
        ("systemd_user_restart", "skipped"),
        ("final_check", "skipped"),
    ]
    assert deployable["sent"]["taken"] == []
    assert "git pull" not in deployable["sent"]["events"]
    assert "migrate" not in deployable["sent"]["events"]
    assert "restart" not in deployable["sent"]["events"]
    assert job["detail"]["before"] == {"git_head": BEFORE}


@pytest.mark.django_db
def test_a_deploy_backs_up_first_then_runs_each_step_and_checks(
    api, deployable, run_jobs
):
    job = deployed(api, deployable, run_jobs)

    assert job["status"] == "succeeded", job
    assert statuses(job) == [
        ("check", "succeeded"),
        ("safety_backup", "succeeded"),
        ("record_env", "succeeded"),
        ("git_pull", "succeeded"),
        ("migrate", "succeeded"),
        ("systemd_user_restart", "succeeded"),
        ("final_check", "succeeded"),
    ]
    assert deployable["sent"]["events"] == [
        f"backup {TARGET}",
        "git pull",
        "migrate",
        "restart",
    ]
    detail = job["detail"]
    assert (detail["before"], detail["after"]) == (
        {"git_head": BEFORE},
        {"git_head": AFTER},
    )
    safety = BackupFileRepository().get(detail["safety_backup"])
    assert (safety.application_id, safety.kind) == (
        deployable["target"].pk,
        BackupFile.Kind.DBS,
    )
    assert "target_env_version" in detail
    [pulled] = [run for run in ran(deployable, ["git", "-C"]) if "pull" in run["argv"]]
    assert "export GIT_TERMINAL_PROMPT=0" in pulled["setup"]
    [migrated] = ran(deployable, MIGRATE)
    assert migrated["timeout"] >= 30 * 60


@pytest.mark.django_db
def test_every_deploy_step_is_audited_against_the_application(
    api, deployable, run_jobs
):
    deployed(api, deployable, run_jobs)

    for action in (
        "deploy.check",
        "deploy.safety_backup",
        "deploy.git_pull",
        "deploy.migrate",
        "deploy.systemd_user_restart",
        "deploy.final_check",
    ):
        [entry] = logged(action)
        assert (entry.status, entry.subject) == (
            audit.SUCCEEDED,
            str(deployable["target"].pk),
        )
    [job] = logged("redeploy.deploy")
    assert job.data["deploy_steps"][0]["kind"] == "git_pull"


@pytest.mark.django_db
def test_a_failing_step_stops_the_deploy_and_offers_the_safety_backup(
    api, deployable, run_jobs
):
    deployable["hosts"].answer(TARGET, MIGRATE, (1, "", "relation exists"))

    job = deployed(api, deployable, run_jobs)

    assert (job["status"], job["error_code"]) == ("failed", "remote_command_failed")
    assert statuses(job)[4:] == [
        ("migrate", "failed"),
        ("systemd_user_restart", "skipped"),
        ("final_check", "skipped"),
    ]
    assert job["detail"]["failed_step"] == "migrate"
    assert job["detail"]["revertable"] is True
    assert "restart" not in deployable["sent"]["events"]


@pytest.mark.django_db
def test_restoring_the_safety_backup_after_a_failed_deploy_leaves_the_env_alone(
    api, deployable, run_jobs
):
    deployable["hosts"].answer(TARGET, MIGRATE, (1, "", "relation exists"))
    failed = deployed(api, deployable, run_jobs)
    env_before = deployable["env"].read_bytes()

    with run_jobs():
        response = api.post(
            f"/api/redeploy/{failed['id']}/revert/",
            {"rehearsal": False, "password": PASSWORD, "confirm_name": "web-2"},
            format="json",
        )
    job = job_of(api, response)

    assert job["status"] == "succeeded", job
    assert statuses(job) == [
        ("check", "succeeded"),
        ("env", "skipped"),
        ("restore", "succeeded"),
    ]
    [restore] = deployable["sent"]["restores"]
    assert "--flush" in restore["argv"]
    assert deployable["env"].read_bytes() == env_before


@pytest.mark.django_db
def test_a_deploy_that_stops_at_the_check_offers_nothing_to_restore(
    api, deployable, run_jobs
):
    deployable["hosts"].answer(
        TARGET, [PYTHON, "manage.py", "dbs_backup", "--help"], (1, "", "no")
    )

    job = deployed(api, deployable, run_jobs)

    assert (job["status"], job["error_code"]) == ("failed", "target_not_ready")
    assert job["detail"]["revertable"] is False
    assert deployable["sent"]["taken"] == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    "fields, code",
    [
        ({"password": ""}, "invalid"),
        ({"confirm_name": "web-3"}, "confirm_name_mismatch"),
        ({"password": "not-it"}, "invalid_password"),
    ],
)
def test_a_real_deploy_needs_the_name_and_the_password(api, deployable, fields, code):
    body = {"rehearsal": False, "password": PASSWORD, "confirm_name": "web-2", **fields}

    response = api.post(deploy_url(deployable["target"]), body, format="json")

    assert response.status_code in (400, 403)
    assert response.json()["error"]["code"] == code
    assert deployable["sent"]["events"] == []


@pytest.mark.django_db
def test_an_application_without_steps_has_nothing_to_deploy(api, world):
    response = api.post(deploy_url(world["target"]), {}, format="json")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_deploy_steps"


@pytest.mark.django_db
def test_an_operator_may_rehearse_a_deploy_but_not_run_one(deployable, run_jobs):
    operator = UserRepository().create(
        username="omar", password=PASSWORD, role=Role.OPERATOR
    )
    client = APIClient()
    client.force_login(operator)
    target = deployable["target"]

    with run_jobs():
        rehearsed = client.post(deploy_url(target), {}, format="json")
    real = client.post(
        deploy_url(target),
        {"rehearsal": False, "password": PASSWORD, "confirm_name": "web-2"},
        format="json",
    )

    assert rehearsed.status_code == 202
    assert real.status_code == 403
    assert real.json()["error"]["code"] == "role_required"


@pytest.mark.django_db
def test_deploy_steps_are_checked_and_saved_with_the_password(api, world):
    target = world["target"]

    saved = api.put(
        steps_url(target), {"steps": STEPS, "account_password": PASSWORD}, format="json"
    )
    without = api.put(steps_url(target), {"steps": STEPS}, format="json")
    wrong = api.put(
        steps_url(target),
        {
            "steps": [{"kind": "compose_up"}, {"kind": "git_pull", "options": {"branch": "-x"}}],
            "account_password": PASSWORD,
        },
        format="json",
    )

    assert saved.status_code == 200, saved.json()
    assert [step["kind"] for step in saved.json()["deploy_steps"]] == [
        "git_pull",
        "migrate",
        "systemd_user_restart",
    ]
    assert saved.json()["deploy_steps"][1]["timeout_minutes"] == 30
    assert without.status_code == 400
    assert wrong.status_code == 400
    assert wrong.json()["error"]["fields"] == {
        "steps.0": ["compose_required"],
        "steps.1": ["invalid_name"],
    }
    [entry] = AuditEvent.objects.filter(action="application.deploy_steps")
    assert entry.data == {"steps": ["git_pull", "migrate", "systemd_user_restart"]}


@pytest.mark.django_db
def test_an_operator_cannot_change_deploy_steps(world):
    operator = UserRepository().create(
        username="omar", password=PASSWORD, role=Role.OPERATOR
    )
    client = APIClient()
    client.force_login(operator)

    response = client.put(
        steps_url(world["target"]),
        {"steps": STEPS, "account_password": PASSWORD},
        format="json",
    )

    assert response.status_code == 403
    assert ApplicationRepository().get(world["target"].pk).deploy_steps == []


@pytest.mark.django_db
def test_steps_that_no_longer_fit_the_application_stop_the_deploy_before_it_starts(
    api, deployable
):
    ApplicationRepository().update(deployable["target"], project_dir="")

    response = api.post(deploy_url(deployable["target"]), {}, format="json")

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"steps.0": ["project_dir_required"]}
