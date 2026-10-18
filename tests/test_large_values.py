import hashlib
import io
import json
import os
import tracemalloc

import pytest
from django.core.management import call_command

from dbs import ModelBackup, restore_backup, validate_backup, write_backup
from dbs.registry import BackupRegistry
from dbs.serialize import Pages, serialize_batches
from tests.conftest import FAST_KDF
from tests.largeapp.models import Blob
from tests.test_stream_backup import BinaryStdout, Receiver

PASS = "large-values-pass-phrase"
MEBIBYTE = 1024 * 1024
SIZE = int(os.environ.get("DBS_LARGE_VALUE_MB", "8")) * MEBIBYTE
BACKUP_BUDGET = 3.5
RESTORE_BUDGET = 3.5
SLACK = 8 * MEBIBYTE


def registry():
    chosen = BackupRegistry()
    chosen.register(Blob)
    return chosen


def peak(action):
    tracemalloc.start()
    try:
        action()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def digest(value):
    return hashlib.sha256(bytes(value) if not isinstance(value, str) else value.encode()).hexdigest()


def text_of(size):
    line = 'a line with "quotes", a \\ backslash, a tab\tand an ending\n'
    return (line * (size // len(line) + 1))[:size]


@pytest.mark.django_db
def test_a_row_holding_a_large_binary_value_round_trips_within_its_budget(tmp_path):
    value = os.urandom(SIZE)
    expected = digest(value)
    Blob.objects.create(name="binary", data=value, text="")
    del value
    output = tmp_path / "binary.dbs"

    backup_peak = peak(lambda: write_backup(output, PASS, registry=registry(), kdf_params=FAST_KDF))
    Blob.objects.all().delete()
    restore_peak = peak(lambda: restore_backup(output, PASS, registry=registry()))

    assert digest(Blob.objects.get(name="binary").data) == expected
    assert backup_peak < BACKUP_BUDGET * SIZE + SLACK
    assert restore_peak < RESTORE_BUDGET * SIZE + SLACK


@pytest.mark.django_db
def test_a_row_holding_large_text_that_needs_escaping_round_trips(tmp_path):
    value = text_of(SIZE)
    expected = digest(value)
    Blob.objects.create(name="text", text=value, data=b"")
    del value
    output = tmp_path / "text.dbs"

    backup_peak = peak(lambda: write_backup(output, PASS, registry=registry(), kdf_params=FAST_KDF))
    Blob.objects.all().delete()
    restore_peak = peak(lambda: restore_backup(output, PASS, registry=registry()))

    assert digest(Blob.objects.get(name="text").text) == expected
    assert backup_peak < BACKUP_BUDGET * SIZE + SLACK
    assert restore_peak < RESTORE_BUDGET * SIZE + SLACK


@pytest.mark.django_db
def test_a_large_row_streams_to_standard_output_and_validates(tmp_path):
    Blob.objects.create(name="streamed", data=os.urandom(SIZE), text="")
    receiver = Receiver()
    stderr = io.StringIO()

    call_command(
        "dbs_backup",
        "--stream",
        output_dir=str(tmp_path),
        passphrase=PASS,
        kdf_time=1,
        kdf_memory=8192,
        stdout=BinaryStdout(receiver),
        stderr=stderr,
    )

    summary = json.loads(stderr.getvalue().splitlines()[-1])
    assert summary["size"] == len(receiver.received)
    assert validate_backup(bytes(receiver.received), PASS).ok


@pytest.mark.django_db
def test_large_and_small_rows_share_a_table_in_order(tmp_path):
    small = [Blob.objects.create(name=f"small {index}", text="x") for index in range(3)]
    large = Blob.objects.create(name="large", data=os.urandom(2 * MEBIBYTE), text="")
    tail = Blob.objects.create(name="tail", text="y")
    output = tmp_path / "mixed.dbs"

    write_backup(output, PASS, registry=registry(), kdf_params=FAST_KDF)
    Blob.objects.all().delete()
    restore_backup(output, PASS, registry=registry())

    names = list(Blob.objects.order_by("pk").values_list("name", flat=True))
    assert names == [row.name for row in [*small, large, tail]]
    assert len(Blob.objects.get(name="large").data) == 2 * MEBIBYTE


@pytest.mark.django_db
def test_batches_stay_under_their_byte_budget():
    for index in range(40):
        Blob.objects.create(name=f"row {index}", text="z" * 4096)

    batches = list(
        serialize_batches(Blob, ModelBackup(), set(), frozenset(), "default", budget=20_000)
    )

    assert sum(count for _pieces, count in batches) == 40
    assert len(batches) > 1
    for pieces, _count in batches:
        assert sum(len(piece) for piece in pieces) <= 20_000 + 4096 + 200


@pytest.mark.django_db
def test_heavy_models_start_with_small_pages_and_grow():
    for index in range(10):
        Blob.objects.create(name=f"row {index}", text="t")
    pages = Pages(Blob.objects.all(), 500)

    sizes = []
    for chunk in pages:
        sizes.append(len(chunk))
        pages.measured(100 * len(chunk), len(chunk))

    assert sizes[0] == 1
    assert sizes[1] == 2
    assert sum(sizes) == 10


@pytest.mark.django_db
def test_pages_follow_uuid_keys_and_custom_querysets():
    import datetime

    from tests.complexapp.models import Publisher

    created = [
        Publisher.objects.create(
            name_en=f"house {index}", name_ar="دار", established=datetime.date(2000, 1, 1)
        )
        for index in range(7)
    ]

    seen = [item.pk for chunk in Pages(Publisher.objects.all(), 3, adaptive=False) for item in chunk]

    assert seen == sorted(item.pk for item in created)

    chosen = [
        item.name_en
        for chunk in Pages(Publisher.objects.filter(name_en__endswith="3"), 1, adaptive=False)
        for item in chunk
    ]
    assert chosen == ["house 3"]


@pytest.mark.django_db
def test_a_sliced_queryset_is_read_in_its_own_order():
    for index in range(5):
        Blob.objects.create(name=f"row {index}", text="t")

    sliced = Blob.objects.order_by("-pk")[:2]
    seen = [item.name for chunk in Pages(sliced, 500) for item in chunk]

    assert seen == ["row 4", "row 3"]
