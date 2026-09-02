"""The packaged version and the importable version must never drift apart."""

import pathlib
import re

import dbs

PYPROJECT = pathlib.Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_pyproject_and_package_agree():
    match = re.search(r'^version = "([^"]+)"', PYPROJECT.read_text(), re.MULTILINE)
    assert match, "pyproject.toml has no version line"
    assert match.group(1) == dbs.__version__


def test_the_wheel_would_carry_the_data_files():
    import tomllib

    with open(PYPROJECT, "rb") as handle:
        config = tomllib.load(handle)

    patterns = config["tool"]["setuptools"]["package-data"]["dbs"]
    for needed in (
        "security/baseline.json.gz",
        "ai/*.md",
        "ai/reference/*.md",
        "static/dbs/*",
        "templates/admin/dbs/*.html",
        "templates/admin/dbs/wiki/*.html",
    ):
        assert needed in patterns, needed


def test_scikit_learn_is_declared():
    import tomllib

    with open(PYPROJECT, "rb") as handle:
        config = tomllib.load(handle)

    assert any(
        dependency.startswith("scikit-learn")
        for dependency in config["project"]["dependencies"]
    )
