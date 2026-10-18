import os
from pathlib import Path

import pytest

from tests.load.runner import Config, run, write_report

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "restored"])


def test_a_backup_taken_under_load_keeps_the_site_answering(tmp_path, settings):
    os.makedirs(settings.DBS_BACKUP_DIR, exist_ok=True)
    config = Config(
        folder=tmp_path,
        rows=int(os.environ.get("DBS_LOAD_ROWS", "20000")),
        customers=500,
        clients=4,
        threads=8,
        baseline=float(os.environ.get("DBS_LOAD_BASELINE", "8")),
        after=float(os.environ.get("DBS_LOAD_AFTER", "5")),
        during_limit=600,
        p95_factor=float(os.environ.get("DBS_LOAD_P95_FACTOR", "3")),
        p95_floor_ms=float(os.environ.get("DBS_LOAD_P95_FLOOR_MS", "50")),
    )

    report = run(config)
    written, _ = write_report(report, Path(os.environ.get("DBS_LOAD_REPORT_DIR", tmp_path)))

    print("\n" + written.read_text())
    failed = [item for item in report["checks"] if not item["passed"]]
    assert not failed, failed
    assert report["phases"]["during"]["requests"] > 0
