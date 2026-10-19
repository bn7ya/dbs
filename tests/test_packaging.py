import importlib
import re

import pytest

from dbs import extras
from tests.test_version import read_pyproject

MODULES = {
    "numpy": "numpy",
    "scikit-learn": "sklearn",
    "paramiko": "paramiko",
    "djangorestframework": "rest_framework",
    "waitress": "waitress",
    "keyring": "keyring",
}
EVERYTHING = {
    "django",
    "cryptography",
    "argon2-cffi",
    "reedsolo",
    "numpy",
    "scikit-learn",
    "djangorestframework",
    "waitress",
    "paramiko",
    "keyring",
}
REQUIREMENT = re.compile(r"^(?P<name>[A-Za-z0-9_.-]+)(\[[^\]]*\])?(?P<spec>[^;]*)(;(?P<marker>.*))?$")
COMMAND_NAMES = ("django-dbs", "django_dbs", "dbs")


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


def test_one_install_brings_everything_dbs_uses():
    names = {parsed(requirement)[0] for requirement in project()["dependencies"]}

    assert names == EVERYTHING


def test_the_old_extra_names_install_nothing_more():
    optional = project()["optional-dependencies"]

    assert set(optional) == {*extras.RETIRED_EXTRAS, "dev"}
    for name in extras.RETIRED_EXTRAS:
        assert optional[name] == [], name
    assert not any(parsed(item)[0] == "django-dbs" for item in optional["dev"])


def test_the_modules_dbs_checks_match_its_dependencies():
    declared = {parsed(requirement)[0] for requirement in project()["dependencies"]}

    assert {MODULES[name] for name in declared if name in MODULES} == set(extras.BUNDLED)


@pytest.mark.parametrize("requirement", sorted(set(every_requirement())))
def test_every_dependency_is_bounded_on_both_sides(requirement):
    name, spec, _ = parsed(requirement)

    assert ">=" in spec, requirement
    assert "<" in spec.replace("<=", ""), requirement


def test_the_classifiers_name_every_django_the_bounds_allow():
    classifiers = set(project()["classifiers"])

    for version in ("4.2", "5.2", "6.0", "6.1"):
        assert f"Framework :: Django :: {version}" in classifiers
    for version in ("3.9", "3.10", "3.11", "3.12", "3.13"):
        assert f"Programming Language :: Python :: {version}" in classifiers


@pytest.mark.parametrize("name", COMMAND_NAMES)
def test_every_command_name_starts_the_manager_cli(name):
    target = project()["scripts"][name]
    module, _, function = target.partition(":")

    assert target == "dbs.manager.cli:main"
    assert callable(getattr(importlib.import_module(module), function))
