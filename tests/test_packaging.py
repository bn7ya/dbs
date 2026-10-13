import re

import pytest

from dbs import extras
from tests.test_version import read_pyproject

MODULES = {
    "scikit-learn": "sklearn",
    "paramiko": "paramiko",
    "djangorestframework": "rest_framework",
    "waitress": "waitress",
    "keyring": "keyring",
}
LIBRARY_ONLY = {"django", "cryptography", "argon2-cffi", "reedsolo", "numpy"}
REQUIREMENT = re.compile(r"^(?P<name>[A-Za-z0-9_.-]+)(\[[^\]]*\])?(?P<spec>[^;]*)(;(?P<marker>.*))?$")


def parsed(requirement):
    match = REQUIREMENT.match(requirement.strip())
    return match.group("name").lower(), match.group("spec").strip(), match.group("marker")


def project():
    return read_pyproject()["project"]


def every_requirement():
    config = project()
    yield from config["dependencies"]
    for requirements in config["optional-dependencies"].values():
        yield from requirements


def test_a_django_project_installs_the_backup_library_alone():
    names = {parsed(requirement)[0] for requirement in project()["dependencies"]}

    assert {"django", "cryptography", "argon2-cffi", "reedsolo"} <= names
    assert names <= LIBRARY_ONLY


def test_each_part_of_dbs_has_its_extra():
    optional = project()["optional-dependencies"]

    assert set(optional) == {"guard", "ssh", "manager", "all", "dev"}
    assert optional["all"] == ["django-dbs[guard,manager,ssh]"]
    assert "django-dbs[all]" in optional["dev"]


@pytest.mark.parametrize("extra", sorted(extras.EXTRAS))
def test_the_modules_dbs_checks_match_each_extra(extra):
    declared = project()["optional-dependencies"][extra]
    required = {
        MODULES[name]
        for name, _, marker in map(parsed, declared)
        if marker is None
    }

    assert required == set(extras.EXTRAS[extra])


@pytest.mark.parametrize("requirement", sorted(set(every_requirement())))
def test_every_dependency_is_bounded_on_both_sides(requirement):
    name, spec, _ = parsed(requirement)
    if name == "django-dbs":
        return

    assert ">=" in spec, requirement
    assert "<" in spec.replace("<=", ""), requirement


def test_the_classifiers_name_every_django_the_bounds_allow():
    classifiers = set(project()["classifiers"])

    for version in ("4.2", "5.2", "6.0", "6.1"):
        assert f"Framework :: Django :: {version}" in classifiers
    for version in ("3.9", "3.10", "3.11", "3.12", "3.13"):
        assert f"Programming Language :: Python :: {version}" in classifiers
