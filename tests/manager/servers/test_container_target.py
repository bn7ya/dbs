from __future__ import annotations

import pytest

from dbs.manager.servers.gateways import ENGINES, ContainerTarget

FILES = ("compose.yaml", "compose.prod.yaml")
COMMAND = ["python", "manage.py", "dbs_backup", "--stream"]


def compose(engine: str, **fields) -> ContainerTarget:
    return ContainerTarget(
        engine=engine, service="backend", files=FILES, project="shop", **fields
    )


def container(engine: str, **fields) -> ContainerTarget:
    return ContainerTarget(engine=engine, container="shop-web-1", **fields)


def compose_prefix(engine: str) -> list[str]:
    return [
        engine,
        "compose",
        "-f",
        "compose.yaml",
        "-f",
        "compose.prod.yaml",
        "-p",
        "shop",
    ]


def test_both_engines_are_known():
    assert ENGINES == ("docker", "podman")


@pytest.mark.parametrize("engine", ENGINES)
def test_a_compose_command_names_its_files_and_project_before_the_verb(engine):
    assert compose(engine).argv("ps", "--services") == [
        *compose_prefix(engine),
        "ps",
        "--services",
    ]


@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize("stdin", [False, True])
def test_a_compose_exec_never_asks_for_a_terminal_with_or_without_stdin(engine, stdin):
    assert compose(engine).exec_argv(COMMAND, stdin=stdin) == [
        *compose_prefix(engine),
        "exec",
        "-T",
        "backend",
        *COMMAND,
    ]


@pytest.mark.parametrize("engine", ENGINES)
def test_a_container_exec_keeps_stdin_open_only_when_something_is_sent(engine):
    target = container(engine)

    assert target.exec_argv(COMMAND) == [engine, "exec", "shop-web-1", *COMMAND]
    assert target.exec_argv(COMMAND, stdin=True) == [
        engine,
        "exec",
        "-i",
        "shop-web-1",
        *COMMAND,
    ]


@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize("stdin", [False, True])
def test_a_compose_exec_carries_user_workdir_and_settings_before_the_service(
    engine, stdin
):
    target = compose(engine, workdir="/app")

    argv = target.exec_argv(
        COMMAND, settings_module="shop.settings.prod", user="10001", stdin=stdin
    )

    assert argv == [
        *compose_prefix(engine),
        "exec",
        "-T",
        "-u",
        "10001",
        "-w",
        "/app",
        "-e",
        "DJANGO_SETTINGS_MODULE=shop.settings.prod",
        "backend",
        *COMMAND,
    ]


@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize(("stdin", "interactive"), [(False, []), (True, ["-i"])])
def test_a_container_exec_carries_user_workdir_and_settings_before_the_container(
    engine, stdin, interactive
):
    target = container(engine, workdir="/code")

    argv = target.exec_argv(
        COMMAND, settings_module="shop.settings.prod", user="app", stdin=stdin
    )

    assert argv == [
        engine,
        "exec",
        *interactive,
        "-u",
        "app",
        "-w",
        "/code",
        "-e",
        "DJANGO_SETTINGS_MODULE=shop.settings.prod",
        "shop-web-1",
        *COMMAND,
    ]


def test_without_files_or_project_compose_finds_them_itself():
    assert ContainerTarget(service="web").exec_argv(["id"]) == [
        "docker",
        "compose",
        "exec",
        "-T",
        "web",
        "id",
    ]


def test_an_argument_that_looks_like_an_option_stays_part_of_the_command():
    argv = container("docker").exec_argv(["rm", "-f", "--", "-rf"])

    assert argv == ["docker", "exec", "shop-web-1", "rm", "-f", "--", "-rf"]


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        (compose("docker"), ["docker", "compose", "version", "--short"]),
        (compose("podman"), ["podman", "compose", "version", "--short"]),
        (
            container("docker"),
            ["docker", "version", "--format", "{{.Server.Version}}"],
        ),
        (container("podman"), ["podman", "version", "--format", "{{.Version}}"]),
    ],
)
def test_the_version_asked_is_compose_for_a_service_and_the_engine_for_a_container(
    target, expected
):
    assert target.version_argv() == expected


@pytest.mark.parametrize("engine", ENGINES)
def test_a_service_is_running_when_the_engine_lists_a_running_container_of_it(engine):
    target = compose(engine)

    assert target.running_argv() == [
        engine,
        "ps",
        "--filter",
        "label=com.docker.compose.project=shop",
        "--filter",
        "label=com.docker.compose.service=backend",
        "--filter",
        "status=running",
        "--format",
        "{{.Names}}",
    ]
    assert target.running_in("shop-backend-1\n") is True
    assert target.running_in("\n") is False
    assert target.running_in("") is False


def test_a_service_without_a_project_name_is_looked_for_by_its_service_alone():
    target = ContainerTarget(engine="podman", service="backend", files=FILES)

    assert "label=com.docker.compose.project=shop" not in target.running_argv()
    assert "label=com.docker.compose.service=backend" in target.running_argv()


@pytest.mark.parametrize("engine", ENGINES)
def test_a_container_is_running_when_the_engine_says_true(engine):
    target = container(engine)

    assert target.running_argv() == [
        engine,
        "inspect",
        "--format",
        "{{.State.Running}}",
        "shop-web-1",
    ]
    assert target.running_in("true\n") is True
    assert target.running_in("false\n") is False
    assert target.running_in("") is False


def test_a_target_is_named_by_its_service_or_its_container():
    assert (compose("docker").name, compose("docker").in_compose) == ("backend", True)
    assert (container("docker").name, container("docker").in_compose) == (
        "shop-web-1",
        False,
    )
