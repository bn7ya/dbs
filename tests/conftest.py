"""Shared fixtures for the DBS test suite."""

import os
from datetime import timedelta
from functools import partial
from pathlib import Path

import pytest
from django.utils import timezone

from dbs.crypto.kdf import KDFParams
from tests.fake_ssh import FakeParamiko

CLOCK_ENV = "DBS_TEST_HOUR"
SESSIONS = {
    Path(__file__).parent / "manager": "tests.manager.settings",
    Path(__file__).parent / "isolation": "tests.isolation.settings",
    Path(__file__).parent / "scale": "tests.scale.settings",
    Path(__file__).parent / "load": "tests.load.settings",
    Path(__file__).parent / "scaling": "tests.scaling.settings",
}


def pytest_ignore_collect(collection_path, config):
    active = os.environ.get("DJANGO_SETTINGS_MODULE")
    path = Path(collection_path)
    for folder, settings_module in SESSIONS.items():
        if path == folder or folder in path.parents:
            return None if active == settings_module else True
    return None

# Fast KDF parameters so the suite isn't dominated by Argon2 cost. Real backups
# use the much stronger defaults in ``KDFParams``.
FAST_KDF = KDFParams(time_cost=1, memory_cost=8 * 1024, parallelism=1)


@pytest.fixture
def fast_kdf():
    return FAST_KDF


@pytest.fixture
def committed(django_capture_on_commit_callbacks):
    return partial(django_capture_on_commit_callbacks, execute=True)


@pytest.fixture
def fake_ssh(tmp_path, monkeypatch):
    root = tmp_path / "remote-host"
    root.mkdir()
    fake = FakeParamiko(str(root))
    monkeypatch.setattr("dbs.transports.ssh._paramiko", lambda: fake)
    return fake


@pytest.fixture
def inline_jobs(monkeypatch):
    from dbs import jobs

    monkeypatch.setattr(jobs, "launch", lambda work, name="dbs-job": work())


@pytest.fixture(autouse=True)
def shifted_clock(monkeypatch):
    target = os.environ.get(CLOCK_ENV)
    if not target:
        return
    real_now = timezone.now
    offset = timedelta(hours=int(target) - real_now().hour)
    monkeypatch.setattr(timezone, "now", lambda: real_now() + offset)
