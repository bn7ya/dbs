from __future__ import annotations

import pytest

from dbs.manager.relocation.systems import DEBIAN, FEDORA, RHEL, os_release, system_of

DEBIAN_12 = """PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"
NAME="Debian GNU/Linux"
VERSION_ID="12"
VERSION="12 (bookworm)"
VERSION_CODENAME=bookworm
ID=debian
"""
UBUNTU_24 = """NAME="Ubuntu"
VERSION_ID="24.04"
ID=ubuntu
ID_LIKE=debian
UBUNTU_CODENAME=noble
VERSION_CODENAME=noble
"""
ROCKY_9 = """NAME="Rocky Linux"
VERSION="9.4 (Blue Onyx)"
ID="rocky"
ID_LIKE="rhel centos fedora"
VERSION_ID="9.4"
"""


def test_os_release_reads_quoted_and_bare_values():
    assert os_release(DEBIAN_12)["PRETTY_NAME"] == "Debian GNU/Linux 12 (bookworm)"
    assert os_release(ROCKY_9)["ID_LIKE"] == "rhel centos fedora"


@pytest.mark.parametrize(
    ("text", "machine", "family", "codename", "architecture"),
    [
        (DEBIAN_12, "x86_64", DEBIAN, "bookworm", "amd64"),
        (UBUNTU_24, "aarch64", DEBIAN, "noble", "arm64"),
        (ROCKY_9, "x86_64", RHEL, "", "amd64"),
        ('ID=almalinux\nVERSION_ID="8.10"\n', "x86_64", RHEL, "", "amd64"),
        ('ID="rhel"\nVERSION_ID="10.0"\n', "x86_64", RHEL, "", "amd64"),
        ('ID=centos\nVERSION_ID="9"\n', "x86_64", RHEL, "", "amd64"),
        ("ID=fedora\nVERSION_ID=41\n", "x86_64", FEDORA, "", "amd64"),
    ],
)
def test_supported_systems(text, machine, family, codename, architecture):
    system = system_of(text, machine)

    assert (system.family, system.codename, system.architecture) == (
        family,
        codename,
        architecture,
    )
    assert system.supported


@pytest.mark.parametrize(
    ("text", "machine"),
    [
        ('ID=centos\nVERSION_ID="7"\n', "x86_64"),
        ("ID=arch\n", "x86_64"),
        ('ID=alpine\nVERSION_ID="3.20.0"\n', "x86_64"),
        ('ID=ubuntu\nVERSION_ID="20.04"\n', "x86_64"),
        ("ID=fedora\nVERSION_ID=38\n", "x86_64"),
        (DEBIAN_12, "riscv64"),
        ("", "x86_64"),
    ],
)
def test_other_systems_are_refused(text, machine):
    assert not system_of(text, machine).supported


def test_a_codename_that_is_not_a_word_is_dropped():
    system = system_of('ID=debian\nVERSION_ID="12"\nVERSION_CODENAME="book worm"\n', "x86_64")

    assert system.codename == ""
