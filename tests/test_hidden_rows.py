import pytest
from django.db import connection

from dbs.engine import create_backup, restore_backup
from dbs.engine.restore import read_payload
from dbs.registry import BackupRegistry
from tests.conftest import FAST_KDF
from tests.softdeleteapp.models import Category, Item

PASS = "hidden-rows-pass-phrase"


def _registry():
    registry = BackupRegistry()
    registry.register(Category)
    registry.register(Item)
    return registry


def _wipe():
    Item.labels.through.objects.all().delete()
    Item.all_objects.all().delete()
    Category.all_objects.all().delete()


@pytest.fixture
def soft_deleted_graph(db):
    live = Category.objects.create(name="live")
    hidden = Category.objects.create(name="hidden", is_deleted=True)
    visible_item = Item.objects.create(name="visible", category=hidden)
    visible_item.labels.set([live, hidden])
    hidden_item = Item.objects.create(name="archived", category=live, is_deleted=True)
    hidden_item.labels.set([hidden])
    return {"live": live, "hidden": hidden, "visible": visible_item, "archived": hidden_item}


def test_default_manager_hides_rows(soft_deleted_graph):
    assert list(Category.objects.values_list("name", flat=True)) == ["live"]
    assert list(Item.objects.values_list("name", flat=True)) == ["visible"]


@pytest.mark.parametrize("flush", [False, True])
def test_rows_hidden_by_the_default_manager_round_trip(soft_deleted_graph, flush):
    graph = soft_deleted_graph
    container = create_backup(PASS, registry=_registry(), kdf_params=FAST_KDF)
    _wipe()
    assert not Category.all_objects.exists()

    out = restore_backup(container, PASS, flush=flush)

    assert out.records_loaded == 4
    hidden = Category.all_objects.get(pk=graph["hidden"].pk)
    assert hidden.is_deleted
    archived = Item.all_objects.get(pk=graph["archived"].pk)
    assert archived.is_deleted
    assert archived.category_id == graph["live"].pk

    visible = Item.objects.get(pk=graph["visible"].pk)
    assert visible.category_id == hidden.pk
    through = Item.labels.through.objects
    assert set(through.filter(item=visible).values_list("category_id", flat=True)) == {
        graph["live"].pk,
        hidden.pk,
    }
    assert set(through.filter(item=archived).values_list("category_id", flat=True)) == {
        hidden.pk
    }
    with connection.constraint_checks_disabled():
        connection.check_constraints()


def test_hidden_rows_are_counted_in_the_backup_stats(soft_deleted_graph):
    container = create_backup(PASS, registry=_registry(), kdf_params=FAST_KDF)
    stats = read_payload(container, PASS).document["stats"]["models"]
    assert {entry["model"]: entry["count"] for entry in stats} == {
        "softdeleteapp.category": 2,
        "softdeleteapp.item": 2,
    }
