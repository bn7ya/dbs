"""Shared fixtures for the DBS test suite."""

import pytest

from dbs.crypto.kdf import KDFParams
from tests.fake_ssh import FakeParamiko

# Fast KDF parameters so the suite isn't dominated by Argon2 cost. Real backups
# use the much stronger defaults in ``KDFParams``.
FAST_KDF = KDFParams(time_cost=1, memory_cost=8 * 1024, parallelism=1)


@pytest.fixture
def fast_kdf():
    return FAST_KDF


@pytest.fixture
def fake_ssh(tmp_path, monkeypatch):
    root = tmp_path / "remote-host"
    root.mkdir()
    fake = FakeParamiko(str(root))
    monkeypatch.setattr("dbs.transports.ssh._paramiko", lambda: fake)
    return fake
