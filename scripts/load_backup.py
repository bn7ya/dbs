import argparse
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)


def arguments(argv=None):
    parser = argparse.ArgumentParser(
        description="Serve a small Django app under steady load, take a panel backup "
        "and a streamed backup while it runs, and write load-report.md and .json."
    )
    parser.add_argument("--rows", type=int, default=200_000)
    parser.add_argument("--customers", type=int, default=10_000)
    parser.add_argument("--clients", type=int, default=8)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--baseline", type=float, default=60.0, help="Seconds of load before.")
    parser.add_argument("--after", type=float, default=60.0, help="Seconds of load after.")
    parser.add_argument(
        "--p95-factor",
        type=float,
        default=float(os.environ.get("DBS_LOAD_P95_FACTOR", "2")),
    )
    parser.add_argument("--report-dir", default=".", help="Where to write the report.")
    return parser.parse_args(argv)


def main(argv=None):
    options = arguments(argv)
    folder = Path(tempfile.mkdtemp(prefix="dbs-load-"))
    os.environ["DBS_LOAD_FOLDER"] = str(folder)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.load.settings")

    import django

    django.setup()
    from django.conf import settings
    from django.core.management import call_command

    from tests.load.runner import Config, run, write_report

    os.makedirs(settings.DBS_BACKUP_DIR, exist_ok=True)
    call_command("migrate", run_syncdb=True, verbosity=0)
    report = run(
        Config(
            folder=folder,
            rows=options.rows,
            customers=options.customers,
            clients=options.clients,
            threads=options.threads,
            baseline=options.baseline,
            after=options.after,
            p95_factor=options.p95_factor,
        )
    )
    written, data = write_report(report, Path(options.report_dir))
    print(written.read_text(encoding="utf-8"))
    print(f"Wrote {written} and {data}.")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
