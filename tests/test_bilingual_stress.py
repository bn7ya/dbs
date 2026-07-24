import random

import pytest

from dbs.engine import create_backup, restore_backup, validate_backup
from tests.complexapp import dataset
from tests.complexapp.models import Employee, Review
from tests.conftest import FAST_KDF

PASS = "stress-pass-phrase"
SEED = 20260724

ARABIC_DIACRITICS = "ًٌٍَُِّْ"
ARABIC_INDIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"


@pytest.mark.django_db
def test_bilingual_backup_restore_roundtrip():
    rng = random.Random(SEED)
    dataset.populate(rng)

    for model, expected_count in dataset.COUNTS.items():
        assert model._default_manager.count() == expected_count

    before = dataset.snapshot()
    samples = dataset.sample_rows(rng)
    totals_before = dataset.aggregates()

    container = create_backup(PASS, kdf_params=FAST_KDF)

    result = validate_backup(container, PASS)
    assert result.ok and result.decrypted_ok
    stats = {entry["model"]: entry["count"] for entry in result.stats["models"]}
    for model, expected_count in dataset.COUNTS.items():
        assert stats[model._meta.label_lower] == expected_count

    dataset.wipe()
    for model in dataset.MODELS:
        assert not model._default_manager.exists()

    out = restore_backup(container, PASS)
    assert out.records_loaded == sum(dataset.COUNTS.values())
    assert not out.healed

    assert dataset.snapshot() == before
    dataset.verify_samples(samples)
    assert dataset.aggregates() == totals_before

    bios = " ".join(Employee.objects.values_list("bio", flat=True))
    assert any(mark in bios for mark in ARABIC_DIACRITICS)

    comments = " ".join(Review.objects.values_list("comment", flat=True)[:500])
    assert any(digit in comments for digit in ARABIC_INDIC_DIGITS)
    assert any(ord(char) > 0x1F000 for char in comments)
