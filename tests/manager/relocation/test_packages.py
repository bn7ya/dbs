from __future__ import annotations

import pytest

from dbs.manager.relocation import packages
from dbs.manager.relocation.systems import system_of

DEBIAN_12 = system_of('ID=debian\nVERSION_ID="12"\nVERSION_CODENAME=bookworm\n', "x86_64")
DEBIAN_13 = system_of('ID=debian\nVERSION_ID="13"\nVERSION_CODENAME=trixie\n', "x86_64")
UBUNTU_22 = system_of('ID=ubuntu\nVERSION_ID="22.04"\nVERSION_CODENAME=jammy\n', "x86_64")
UBUNTU_24 = system_of('ID=ubuntu\nVERSION_ID="24.04"\nVERSION_CODENAME=noble\n', "aarch64")
ROCKY_9 = system_of('ID=rocky\nVERSION_ID="9.4"\n', "x86_64")
RHEL_9 = system_of('ID=rhel\nVERSION_ID="9.4"\n', "x86_64")
RHEL_10 = system_of('ID=rhel\nVERSION_ID="10.0"\n', "x86_64")
FEDORA_41 = system_of("ID=fedora\nVERSION_ID=41\n", "x86_64")
SYSTEMS = (DEBIAN_12, DEBIAN_13, UBUNTU_22, UBUNTU_24, ROCKY_9, RHEL_9, RHEL_10, FEDORA_41)


def test_docker_comes_from_dockers_own_repository_with_a_pinned_key():
    plan = packages.resolve(UBUNTU_24, ["docker"], installed=[])

    [repository] = plan.repositories
    assert repository.fingerprint == packages.DOCKER_DEBIAN_KEY
    assert repository.content == (
        "deb [arch=arm64 signed-by=/etc/apt/keyrings/docker.asc] "
        "https://download.docker.com/linux/ubuntu noble stable\n"
    )
    assert plan.packages == [
        "ca-certificates",
        "curl",
        "gnupg",
        "tar",
        *packages.DOCKER_PACKAGES,
    ]
    assert plan.services == ["docker"]


@pytest.mark.parametrize(
    ("system", "channel", "fingerprint"),
    [
        (DEBIAN_12, "debian", packages.DOCKER_DEBIAN_KEY),
        (ROCKY_9, "centos", packages.DOCKER_RPM_KEY),
        (RHEL_9, "rhel", packages.DOCKER_RPM_KEY),
        (FEDORA_41, "fedora", packages.DOCKER_RPM_KEY),
    ],
)
def test_each_family_uses_its_docker_channel(system, channel, fingerprint):
    repository = packages.docker_repository(system)

    assert repository.key_url == f"https://download.docker.com/linux/{channel}/gpg"
    assert repository.fingerprint == fingerprint


def test_what_is_installed_already_is_left_alone():
    plan = packages.resolve(DEBIAN_12, ["git", "nginx"], installed=["git", "nginx"])

    assert plan.empty
    assert plan.services == ["nginx"]


@pytest.mark.parametrize("system", [DEBIAN_12, UBUNTU_22])
def test_podman_without_podman_compose_is_a_blocker(system):
    assert packages.resolve(system, ["podman"], installed=[]).blockers == [
        "compose_provider_unavailable"
    ]


def test_podman_on_rhel_needs_epel_and_rocky_installs_it():
    assert packages.resolve(RHEL_9, ["podman"], installed=[]).blockers == ["epel_required"]
    assert "epel-release" in packages.resolve(ROCKY_9, ["podman"], installed=[]).packages


def test_postgresql_on_rhel_9_enables_a_recent_stream():
    plan = packages.resolve(ROCKY_9, ["postgresql"], installed=[])

    assert plan.modules == ["postgresql:16"]
    assert "postgresql-server" in plan.packages
    assert packages.resolve(RHEL_10, ["postgresql"], installed=[]).modules == []


def test_mysql_on_debian_becomes_mariadb_with_a_note():
    plan = packages.resolve(DEBIAN_12, ["mysql"], installed=[])

    assert "mariadb-server" in plan.packages
    assert plan.notes == ["mysql_replaced_by_mariadb"]
    assert plan.services == ["mariadb"]


@pytest.mark.parametrize(
    ("system", "package", "service"),
    [
        (DEBIAN_12, "redis-server", "redis-server"),
        (ROCKY_9, "redis", "redis"),
        (RHEL_10, "valkey", "valkey"),
        (FEDORA_41, "valkey", "valkey"),
    ],
)
def test_redis_by_system(system, package, service):
    plan = packages.resolve(system, ["redis"], installed=[])

    assert package in plan.packages and plan.services == [service]


def test_rhel_installs_the_sources_python_when_it_is_offered():
    assert packages.python_packages(ROCKY_9, "3.12")[0] == "python3.12"
    assert packages.python_command(ROCKY_9, "3.12") == "/usr/bin/python3.12"
    assert packages.python_packages(ROCKY_9, "3.7")[0] == "python3"
    assert packages.python_command(DEBIAN_12, "3.12") == "/usr/bin/python3"


@pytest.mark.parametrize("system", SYSTEMS)
def test_every_package_name_is_one(system):
    for need in packages.NEEDS:
        assert all(packages.PACKAGE.match(name) for name in packages.packages_for(system, need))


def test_an_unsupported_system_gets_no_plan():
    unsupported = system_of("ID=arch\n", "x86_64")

    assert packages.resolve(unsupported, ["git"], installed=[]).blockers == ["os_unsupported"]
    assert packages.asked_packages(unsupported, ["git"]) == []


def test_installed_packages_are_read_from_dpkg_and_rpm():
    dpkg = "git\tii \nnginx\trc \n"
    rpm = "git\npackage nginx is not installed\n"

    assert packages.missing_from_dpkg(dpkg, ["git", "nginx", "curl"]) == ["nginx", "curl"]
    assert packages.missing_from_rpm(rpm, ["git", "nginx"]) == ["nginx"]
