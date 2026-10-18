from types import SimpleNamespace

import pytest
from rest_framework.exceptions import ValidationError

from dbs.manager.redeploy import catalogue
from dbs.manager.redeploy.catalogue import Place, rehearsal_commands, run_command, validated
from dbs.manager.servers.gateways import ContainerTarget

COMPOSE = ContainerTarget(engine="podman", service="web", files=("compose.yaml",))
HOST_APP = SimpleNamespace(kind="host", project_dir="/srv/shop")
COMPOSE_APP = SimpleNamespace(kind="compose", project_dir="/srv/blog")
CONTAINER_APP = SimpleNamespace(kind="container", project_dir="")


def host_place():
    return Place("host", "/srv/shop", "/srv/shop/.venv/bin/python", None, "", "", "")


def compose_place():
    return Place("compose", "/srv/blog", "python3", COMPOSE.argv, "podman", "", "web")


def errors_of(steps, application):
    with pytest.raises(ValidationError) as caught:
        validated(steps, application)
    return {
        field: [error.code for error in found]
        for field, found in caught.value.detail.items()
    }


def test_valid_steps_come_back_with_their_options_and_timeouts():
    steps = validated(
        [
            {"kind": "git_pull", "options": {"remote": "origin", "branch": "main"}},
            {"kind": "pip_install", "options": {"requirements": "requirements/prod.txt"}},
            {"kind": "migrate", "timeout_minutes": 30},
            {"kind": "systemd_user_restart", "options": {"unit": "shop.service"}},
        ],
        HOST_APP,
    )

    assert steps == [
        {"kind": "git_pull", "options": {"remote": "origin", "branch": "main"}, "timeout_minutes": 10},
        {
            "kind": "pip_install",
            "options": {"requirements": "requirements/prod.txt"},
            "timeout_minutes": 10,
        },
        {"kind": "migrate", "options": {}, "timeout_minutes": 30},
        {"kind": "systemd_user_restart", "options": {"unit": "shop.service"}, "timeout_minutes": 10},
    ]


@pytest.mark.parametrize(
    "step, code",
    [
        ({"kind": "rm_rf"}, "unknown_step"),
        ({"kind": "git_pull", "options": {"branch": "main; rm -rf /"}}, "invalid_name"),
        ({"kind": "git_pull", "options": {"branch": "-x"}}, "invalid_name"),
        ({"kind": "git_pull", "options": {"remote": "origin"}}, "branch_required"),
        ({"kind": "git_pull", "options": {"upload_pack": "x"}}, "unknown_option"),
        ({"kind": "pip_install", "options": {"requirements": "../etc/passwd"}}, "invalid_requirements"),
        ({"kind": "pip_install", "options": {"requirements": "/abs.txt"}}, "invalid_requirements"),
        ({"kind": "pip_install", "options": {"requirements": "-e."}}, "invalid_requirements"),
        ({"kind": "systemd_user_restart", "options": {"unit": "shop"}}, "invalid_unit"),
        ({"kind": "migrate", "timeout_minutes": 0}, "invalid_timeout"),
        ({"kind": "migrate", "timeout_minutes": 121}, "invalid_timeout"),
        ({"kind": "compose_up"}, "compose_required"),
        ({"kind": "restart"}, "container_required"),
    ],
)
def test_a_step_that_does_not_fit_the_catalogue_is_refused(step, code):
    assert code in errors_of([step], HOST_APP)["steps.0"]


def test_compose_steps_take_only_service_names():
    assert "invalid_service" in errors_of(
        [{"kind": "compose_up", "options": {"services": ["web", "--build"]}}], COMPOSE_APP
    )["steps.0"]


def test_steps_that_need_the_host_refuse_a_container_application():
    found = errors_of(
        [
            {"kind": "git_pull"},
            {"kind": "pip_install", "options": {"requirements": "requirements.txt"}},
        ],
        CONTAINER_APP,
    )

    assert found["steps.0"] == ["project_dir_required"]
    assert set(found["steps.1"]) == {"project_dir_required", "host_required"}


def test_an_application_runs_at_most_twelve_steps():
    assert errors_of([{"kind": "migrate"}] * 13, HOST_APP) == {"steps": ["too_many_steps"]}


def test_each_step_runs_a_fixed_command():
    place = compose_place()

    assert run_command({"kind": "git_pull", "options": {}}, host_place()).argv == [
        "git", "-C", "/srv/shop", "pull", "--ff-only", "--no-rebase",
    ]
    pulled = run_command(
        {"kind": "git_pull", "options": {"remote": "origin", "branch": "main"}}, host_place()
    )
    assert pulled.argv[-2:] == ["origin", "main"]
    assert pulled.env == {"GIT_TERMINAL_PROMPT": "0"}
    assert run_command(
        {"kind": "compose_build", "options": {"services": ["web"], "pull": True}}, place
    ).argv == ["podman", "compose", "-f", "compose.yaml", "build", "--pull", "web"]
    assert run_command({"kind": "compose_up", "options": {}}, place).argv == [
        "podman", "compose", "-f", "compose.yaml", "up", "-d",
    ]
    assert run_command({"kind": "restart", "options": {}}, place).argv[-2:] == ["restart", "web"]
    assert run_command(
        {"kind": "restart", "options": {}},
        Place("container", "", "python3", None, "docker", "wiki-web", ""),
    ).argv == ["docker", "restart", "wiki-web"]
    assert run_command(
        {"kind": "systemd_user_restart", "options": {"unit": "shop.service"}}, host_place()
    ).argv == ["systemctl", "--user", "restart", "shop.service"]
    installed = run_command(
        {"kind": "pip_install", "options": {"requirements": "requirements.txt"}}, host_place()
    )
    assert installed.argv == [
        "/srv/shop/.venv/bin/python", "-m", "pip", "install", "-r", "requirements.txt",
    ]
    assert installed.cwd == "/srv/shop"
    migrated = run_command({"kind": "migrate", "options": {}}, place)
    assert migrated.manage and migrated.argv == ["migrate", "--noinput"]


def test_a_rehearsal_only_reads():
    place = compose_place()

    git = rehearsal_commands({"kind": "git_pull", "options": {"remote": "origin", "branch": "main"}}, host_place())
    assert [command.argv[3:] for command in git] == [
        ["fetch", "--dry-run", "origin"],
        ["status", "--porcelain"],
    ]
    assert rehearsal_commands({"kind": "compose_up", "options": {}}, place)[0].argv[-2:] == [
        "config", "--quiet",
    ]
    assert rehearsal_commands({"kind": "migrate", "options": {}}, place)[0].argv == ["migrate", "--plan"]
    assert "--dry-run" in rehearsal_commands({"kind": "collectstatic", "options": {}}, place)[0].argv
    assert rehearsal_commands({"kind": "restart", "options": {}}, place) == []
    pip = rehearsal_commands(
        {"kind": "pip_install", "options": {"requirements": "requirements.txt"}},
        host_place(),
    )
    assert [command.argv for command in pip] == [
        ["/srv/shop/.venv/bin/python", "-m", "pip", "--version"],
        ["test", "-r", "requirements.txt"],
    ]
    assert pip[1].cwd == "/srv/shop"
    assert catalogue.STEPS_MAX == 12
