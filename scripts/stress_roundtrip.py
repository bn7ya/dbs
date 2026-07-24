import os
import random
import sys
import tempfile
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import django
from django.conf import settings

SEED = 20260724
PASSPHRASE = "stress-roundtrip-passphrase"


def configure(db_path):
    settings.configure(
        DEBUG=False,
        SECRET_KEY="dbs-stress-script",
        INSTALLED_APPS=[
            "django.contrib.contenttypes",
            "django.contrib.auth",
            "dbs",
            "tests.complexapp",
        ],
        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": db_path}},
        DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
        USE_TZ=True,
    )
    django.setup()


def main():
    workdir = tempfile.mkdtemp(prefix="dbs-stress-")
    db_path = os.path.join(workdir, "stress.sqlite3")
    backup_path = os.path.join(workdir, "stress.dbs")
    configure(db_path)

    from django.core.management import call_command
    from django.db import connections

    from dbs.engine import create_backup, restore_backup, validate_backup
    from tests.complexapp import dataset

    timings = {}

    def timed(label, func):
        start = time.perf_counter()
        value = func()
        timings[label] = time.perf_counter() - start
        return value

    timed("create schema", lambda: call_command("migrate", run_syncdb=True, verbosity=0))
    timed("populate", lambda: dataset.populate(random.Random(SEED)))

    for model in dataset.MODELS:
        print(f"{model._meta.label}: {model._default_manager.count()} rows")
    print(f"database file: {os.path.getsize(db_path):,} bytes")

    before = timed("snapshot before", dataset.snapshot)
    samples = dataset.sample_rows(random.Random(SEED))
    totals_before = dataset.aggregates()

    timed("backup", lambda: create_backup(PASSPHRASE, kdf_params=dataset.STRESS_KDF, output=backup_path))
    print(f"backup container: {os.path.getsize(backup_path):,} bytes")

    with open(backup_path, "rb") as fh:
        container = fh.read()

    result = timed("validate", lambda: validate_backup(container, PASSPHRASE))
    print(result.summary())
    if not (result.ok and result.decrypted_ok):
        return 1

    connections.close_all()
    os.remove(db_path)
    if os.path.exists(db_path):
        print("database file still present after delete")
        return 1
    print("database file deleted")

    timed("rebuild schema", lambda: call_command("migrate", run_syncdb=True, verbosity=0))
    for model in dataset.MODELS:
        if model._default_manager.exists():
            print(f"{model._meta.label} not empty in the rebuilt database")
            return 1

    out = timed("restore", lambda: restore_backup(container, PASSPHRASE))
    print(f"records restored: {out.records_loaded:,}")
    if out.healed:
        print("container needed healing on a clean roundtrip")
        return 1
    if out.records_loaded != sum(dataset.COUNTS.values()):
        print(f"expected {sum(dataset.COUNTS.values()):,} records")
        return 1

    after = timed("snapshot after", dataset.snapshot)
    if after != before:
        for label, digest in before.items():
            if after.get(label) != digest:
                print(f"mismatch in {label}: {digest} != {after.get(label)}")
        return 1

    dataset.verify_samples(samples)
    if dataset.aggregates() != totals_before:
        print("aggregate totals changed across the roundtrip")
        return 1

    print("restored database matches the original: counts, hashes, samples and aggregates all equal")
    for label, seconds in timings.items():
        print(f"{label}: {seconds:.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
