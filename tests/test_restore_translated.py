import pytest

from dbs.engine import create_backup
from dbs.engine.restore import restore_translated
from tests.conftest import FAST_KDF
from tests.format1 import as_format1
from tests.testapp.models import Author, Tag

PASSPHRASE = "translated-restore-pass"


class AuthorsAlsoTag:
    def labels(self, order):
        if "testapp.tag" in order:
            return order
        return [*order, "testapp.tag"]

    def records(self, record):
        if record["model"] != "testapp.author":
            return [record]
        tag = {
            "model": "testapp.tag",
            "pk": record["pk"],
            "fields": {"label": record["fields"]["name"].lower()},
        }
        return [record, tag]


@pytest.fixture
def authors(db):
    Author.objects.create(pk=7, name="Ada")
    Author.objects.create(pk=8, name="Grace")
    data = create_backup(PASSPHRASE, models=[Author], kdf_params=FAST_KDF)
    Author.objects.all().delete()
    return data


@pytest.mark.django_db
@pytest.mark.parametrize("shape", ["stream", "format1"])
def test_a_translation_turns_one_record_into_several_on_the_way_in(authors, shape):
    data = authors if shape == "stream" else as_format1(authors, PASSPHRASE)

    result = restore_translated(data, PASSPHRASE, AuthorsAlsoTag(), flush=True)

    assert sorted(Author.objects.values_list("pk", "name")) == [(7, "Ada"), (8, "Grace")]
    assert sorted(Tag.objects.values_list("pk", "label")) == [(7, "ada"), (8, "grace")]
    assert result.records_loaded == 4


@pytest.mark.django_db
def test_a_rehearsed_translation_changes_nothing(authors):
    result = restore_translated(authors, PASSPHRASE, AuthorsAlsoTag(), dry_run=True)

    assert result.records_would_load == 4
    assert not Author.objects.exists() and not Tag.objects.exists()
