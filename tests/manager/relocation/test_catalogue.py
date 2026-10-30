from __future__ import annotations

import inspect

import pytest

from dbs.manager.relocation import catalogue
from dbs.manager.relocation.catalogue import Command, ContainerSpec, Mount, Port


def test_a_folder_is_archived_to_stdout_with_anchored_exclusions():
    command = catalogue.tar_create("/srv/shop", ["db.sqlite3", "data/postgres"])

    assert command.argv == (
        "tar",
        "--create",
        "--gzip",
        "--file",
        "-",
        "--anchored",
        "--no-wildcards",
        "--exclude=./db.sqlite3",
        "--exclude=./data/postgres",
        "--directory",
        "/srv/shop",
        "--",
        ".",
    )
    assert not command.root


def test_extraction_keeps_owners_and_never_writes_over_a_file():
    command = catalogue.tar_extract("/home/deploy/.dbs-staging/a.tar.gz", "/srv/.shop.in", numeric=True)

    assert command.root
    assert "--keep-old-files" in command.argv and "--same-owner" in command.argv
    assert command.argv[-1] == "--numeric-owner"
    assert "--numeric-owner" not in catalogue.tar_extract("/a/b", "/c", numeric=False).argv
    as_user = catalogue.tar_extract("/a/b", "/c", numeric=True, root=False)
    assert not as_user.root and "--no-same-owner" in as_user.argv
    assert "--numeric-owner" not in as_user.argv


@pytest.mark.parametrize(
    "build",
    [
        lambda: catalogue.tar_create("relative"),
        lambda: catalogue.tar_create("/srv/../etc"),
        lambda: catalogue.tar_create("/srv/shop", ["-rf"]),
        lambda: catalogue.tar_create("/srv/shop", ["../etc"]),
        lambda: catalogue.tar_create("/srv/shop", ["*.log"]),
        lambda: catalogue.apt_install(["nginx; id"]),
        lambda: catalogue.apt_install(["-oDebug=1"]),
        lambda: catalogue.image_save("docker", "--output=/etc/passwd"),
        lambda: catalogue.image_save("sh", "nginx"),
        lambda: catalogue.volume_create("docker", "-v"),
        lambda: catalogue.systemctl("stop", "nginx"),
        lambda: catalogue.systemctl("enable", "x; reboot"),
        lambda: catalogue.add_to_group("root\nx", "docker"),
        lambda: catalogue.make_folder("/srv/shop", "777", "0", "0"),
        lambda: catalogue.own_user("/srv/shop", "deploy", "1000"),
        lambda: catalogue.own_folder("/srv/shop", "0", "root"),
        lambda: catalogue.folder_mode("/srv/shop", "u+s", root=True),
        lambda: catalogue.folder_mode("/srv/shop", "-R", root=False),
        lambda: catalogue.fetch_key("https://example.com/gpg", "/tmp/k"),
        lambda: catalogue.dnf_module_enable("postgresql:16; id"),
    ],
)
def test_names_that_could_be_read_as_options_or_commands_are_refused(build):
    with pytest.raises(ValueError):
        build()


def test_packages_install_without_prompts():
    assert catalogue.apt_install(["git", "nginx"]).argv == (
        "env",
        "DEBIAN_FRONTEND=noninteractive",
        "NEEDRESTART_MODE=a",
        "apt-get",
        "-o",
        "DPkg::Lock::Timeout=300",
        "install",
        "-y",
        "--no-install-recommends",
        "git",
        "nginx",
    )
    assert catalogue.dnf_install(["git"]).argv == ("dnf", "install", "-y", "git")


def test_the_sources_user_is_mapped_to_the_targets_in_two_passes():
    assert catalogue.own_user("/srv/shop", "1001", "1000").argv == (
        "chown",
        "-R",
        "-h",
        "--from=1001",
        "1000",
        "--",
        "/srv/shop",
    )
    assert catalogue.own_group("/srv/shop", "1001", "1000").argv[3:5] == (
        "--from=:1001",
        ":1000",
    )


def test_the_folder_itself_is_read_and_given_its_owner_and_mode_by_number():
    assert catalogue.folder_owner("/srv/shop").argv == ("stat", "--format=%u:%g:%a", "--", "/srv/shop")
    assert catalogue.own_folder("/srv/shop", "1001", "1001").argv == (
        "chown",
        "-h",
        "1001:1001",
        "--",
        "/srv/shop",
    )
    assert catalogue.folder_mode("/srv/shop", "2775", root=False).argv == ("chmod", "2775", "--", "/srv/shop")


def test_a_folder_moves_into_place_only_where_nothing_is():
    assert catalogue.place("/srv/.shop.in", "/srv/shop").argv == (
        "mv",
        "-T",
        "-n",
        "--",
        "/srv/.shop.in",
        "/srv/shop",
    )
    assert catalogue.copy_new("/a/b", "/etc/x").argv[:3] == ("cp", "-n", "-T")


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (catalogue.ROOT, ["apt-get", "update"]),
        (catalogue.NOPASSWD, ["sudo", "-n", "-k", "--", "apt-get", "update"]),
        (catalogue.PASSWORD, ["sudo", "-S", "-p", "", "-k", "--", "apt-get", "update"]),
    ],
)
def test_privileged_commands_by_sudo_mode(mode, expected):
    assert catalogue.privileged(Command(("apt-get", "update"), root=True), mode) == expected


def test_privileged_commands_as_another_user():
    command = catalogue.postgresql_shell()

    assert catalogue.privileged(command, catalogue.PASSWORD)[:9] == [
        "sudo",
        "-S",
        "-p",
        "",
        "-k",
        "-u",
        "postgres",
        "--",
        "psql",
    ]
    assert catalogue.privileged(command, catalogue.ROOT)[:4] == [
        "runuser",
        "-u",
        "postgres",
        "--",
    ]


def test_a_command_that_needs_no_root_is_run_as_it_is():
    assert catalogue.privileged(catalogue.uname_machine(), catalogue.PASSWORD) == ["uname", "-m"]


def test_without_sudo_nothing_runs_as_root():
    with pytest.raises(ValueError):
        catalogue.privileged(catalogue.apt_update(), catalogue.MISSING)


def test_only_a_password_mode_sudo_reads_a_line_from_stdin():
    assert catalogue.needs_password_line(["sudo", "-S", "-p", "", "-k", "--", "true"])
    assert not catalogue.needs_password_line(["sudo", "-n", "-k", "--", "true"])
    assert not catalogue.needs_password_line(["psql"])


def test_a_container_is_run_again_from_validated_parts():
    spec = ContainerSpec(
        engine="docker",
        name="shop",
        image="registry.example.com/shop:1.4",
        env_file="/home/deploy/.dbs-staging/relocation-7/shop.env",
        ports=(Port("127.0.0.1", 8000, 8000), Port("", 9000, 9000, "udp")),
        mounts=(
            Mount("bind", "/srv/shop/media", "/app/media"),
            Mount("volume", "shop_static", "/app/static", read_only=True),
        ),
        restart="unless-stopped",
        network="shop_net",
        user="1000:1000",
        workdir="/app",
        entrypoint=("/entrypoint.sh", "--wait"),
        command=("gunicorn", "shop.wsgi"),
        labels=(("traefik.enable", "true"),),
    )

    assert catalogue.container_run(spec).argv == (
        "docker",
        "run",
        "--detach",
        "--name",
        "shop",
        "--env-file",
        "/home/deploy/.dbs-staging/relocation-7/shop.env",
        "--publish",
        "127.0.0.1:8000:8000/tcp",
        "--publish",
        "9000:9000/udp",
        "--volume",
        "/srv/shop/media:/app/media",
        "--volume",
        "shop_static:/app/static:ro",
        "--restart",
        "unless-stopped",
        "--network",
        "shop_net",
        "--user",
        "1000:1000",
        "--workdir",
        "/app",
        "--label",
        "traefik.enable=true",
        "--entrypoint",
        "/entrypoint.sh",
        "--",
        "registry.example.com/shop:1.4",
        "--wait",
        "gunicorn",
        "shop.wsgi",
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "--privileged"},
        {"image": "-it"},
        {"restart": "sometimes"},
        {"ports": (Port("", 70000, 80),)},
        {"mounts": (Mount("bind", "relative", "/app"),)},
        {"mounts": (Mount("volume", "-v", "/app"),)},
        {"labels": (("a", "b\nc"),)},
        {"user": "root;id"},
    ],
)
def test_a_container_with_an_invalid_part_is_refused(changes):
    spec = ContainerSpec(**{"engine": "podman", "name": "shop", "image": "shop:1", **changes})

    with pytest.raises(ValueError):
        catalogue.container_run(spec)


def test_no_builder_takes_a_command_line():
    for name, builder in inspect.getmembers(catalogue, inspect.isfunction):
        if builder.__module__ != catalogue.__name__:
            continue
        if inspect.signature(builder).return_annotation != "Command":
            continue
        parameters = inspect.signature(builder).parameters
        assert "argv" not in parameters, name
        assert "command_line" not in parameters, name
