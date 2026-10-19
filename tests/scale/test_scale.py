import os
import resource
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from django.db.models import Count, Max, Min, Sum

from dbs import BackupRegistry, restore_backup, validate_backup, write_backup
from tests.conftest import FAST_KDF
from tests.scale.scaleapp.models import MANY_TO_MANY_EVERY, TABLE_MODELS, Wide

PASS = "scale-pass-phrase"
ROWS = int(os.environ.get("DBS_SCALE_ROWS", "1000000"))
ROWS_PER_TABLE = 3
INSERT_BATCH = 10_000
MEMORY_LIMIT_MB = int(os.environ.get("DBS_SCALE_MEMORY_MB", "1024"))
START = datetime(2026, 1, 1, tzinfo=timezone.utc)

pytestmark = pytest.mark.django_db(transaction=True)


def registry():
    chosen = BackupRegistry()
    for model in [*TABLE_MODELS, Wide]:
        chosen.register(model)
    return chosen


def fill_tables():
    for index, model in enumerate(TABLE_MODELS):
        rows = [
            model(name=f"t{index}-r{row}", value=index * 10 + row)
            for row in range(ROWS_PER_TABLE)
        ]
        if index and hasattr(model, "parent"):
            parent = TABLE_MODELS[index - 1].objects.order_by("pk").first()
            for row in rows:
                row.parent = parent
        model.objects.bulk_create(rows)
        if index and index % MANY_TO_MANY_EVERY == 0:
            peers = list(TABLE_MODELS[index - 1].objects.all())
            for row in model.objects.all():
                row.peers.set(peers)


def fill_wide():
    made = 0
    while made < ROWS:
        count = min(INSERT_BATCH, ROWS - made)
        Wide.objects.bulk_create(
            Wide(
                name=f"row-{made + offset}",
                amount=Decimal(made + offset) / 100,
                created=START + timedelta(seconds=made + offset),
                note="" if (made + offset) % 3 else f"note {made + offset} " * 4,
                flag=bool((made + offset) % 2),
            )
            for offset in range(count)
        )
        made += count


def fingerprint():
    tables = {
        model._meta.db_table: model.objects.aggregate(
            rows=Count("pk"), values=Sum("value"), first=Min("name"), last=Max("name")
        )
        for model in TABLE_MODELS
    }
    peers = {
        model._meta.db_table: model.peers.through.objects.count()
        for model in TABLE_MODELS
        if hasattr(model, "peers")
    }
    wide = Wide.objects.aggregate(
        rows=Count("pk"),
        amount=Sum("amount"),
        first=Min("created"),
        last=Max("created"),
        flags=Count("pk", filter=Wide.objects.filter(flag=True).query.where),
    )
    return tables, peers, wide


def peak_rss_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def test_a_thousand_tables_and_a_large_table_round_trip(tmp_path):
    fill_tables()
    fill_wide()
    before = fingerprint()
    output = tmp_path / "scale.dbs"

    started = time.monotonic()
    summary = write_backup(output, PASS, kdf_params=FAST_KDF, registry=registry())
    backed_up = time.monotonic() - started
    checked = validate_backup(output, PASS)
    started = time.monotonic()
    result = restore_backup(output, PASS, flush=True, registry=registry())
    restored = time.monotonic() - started

    assert summary.verified and checked.ok and checked.decrypted_ok
    assert result.records_loaded >= ROWS + len(TABLE_MODELS) * ROWS_PER_TABLE
    assert fingerprint() == before
    assert peak_rss_mb() < MEMORY_LIMIT_MB
    print(
        f"\nscale: {len(TABLE_MODELS)} tables, {ROWS} wide rows, "
        f"{summary.bytes_written:,} bytes, backup {backed_up:.1f}s, "
        f"restore {restored:.1f}s, peak RSS {peak_rss_mb():.0f} MiB"
    )
