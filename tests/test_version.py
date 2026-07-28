"""The packaged version and the importable version must never drift apart."""

import pathlib
import re

import dbs

PYPROJECT = pathlib.Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_pyproject_and_package_agree():
    match = re.search(r'^version = "([^"]+)"', PYPROJECT.read_text(), re.MULTILINE)
    assert match, "pyproject.toml has no version line"
    assert match.group(1) == dbs.__version__
