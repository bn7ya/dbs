"""Shared fixtures for the DBS test suite."""

import pytest

from dbs.crypto.kdf import KDFParams

# Fast KDF parameters so the suite isn't dominated by Argon2 cost. Real backups
# use the much stronger defaults in ``KDFParams``.
FAST_KDF = KDFParams(time_cost=1, memory_cost=8 * 1024, parallelism=1)


@pytest.fixture
def fast_kdf():
    return FAST_KDF
