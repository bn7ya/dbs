import pytest

from dbs.engine import create_backup
from dbs.engine.restore import read_payload
from dbs.introspect import backup_plan, discover_models
from dbs.registry import BackupRegistry
from tests.conftest import FAST_KDF
from tests.restoreapp.models import Bar, Pizzeria, Place, Restaurant, Venue

PASS = "model-order-pass-phrase"


def _registry(*models):
    registry = BackupRegistry()
    for model in models:
        registry.register(model)
    return registry


def _labels(records):
    return [record["model"] for record in records]


def test_selecting_a_child_brings_in_its_parents_first():
    selected = discover_models(_registry(Pizzeria))

    assert selected == [Place, Restaurant, Pizzeria]


def test_parents_come_before_children_even_through_a_foreign_key_cycle():
    selected = discover_models(_registry(Restaurant, Place))

    assert selected.index(Place) < selected.index(Restaurant)


def test_unmanaged_models_are_left_out_of_discovery():
    assert Venue not in discover_models(BackupRegistry())


def test_an_unmanaged_model_can_still_be_registered():
    assert Venue in discover_models(_registry(Venue))


def test_an_unmanaged_model_comes_back_with_a_minus_entry(settings):
    settings.DBS_EXCLUDE_MODELS = ["-restoreapp.Venue"]

    assert Venue in discover_models(BackupRegistry())


@pytest.mark.django_db
def test_parents_added_for_a_child_carry_only_that_childs_rows():
    plain = Place.objects.create(name="plain")
    diner = Restaurant.objects.create(name="diner")
    pub = Bar.objects.create(name="pub", taps=4)

    container = create_backup(PASS, registry=_registry(Restaurant), kdf_params=FAST_KDF)

    records = read_payload(container, PASS).records
    places = {record["pk"] for record in records if record["model"] == "restoreapp.place"}
    assert places == {diner.pk}
    assert plain.pk not in places and pub.pk not in places


@pytest.mark.django_db
def test_the_backup_records_the_model_order():
    Pizzeria.objects.create(name="slice")

    container = create_backup(PASS, registry=_registry(Pizzeria), kdf_params=FAST_KDF)

    document = read_payload(container, PASS).document
    assert document["order"] == [
        "restoreapp.place",
        "restoreapp.restaurant",
        "restoreapp.pizzeria",
    ]
    assert _labels(document["records"]) == document["order"]


def test_the_plan_keeps_a_registered_parents_own_configuration():
    registry = _registry(Place, Restaurant)

    configs = dict(backup_plan(registry))

    assert configs[Place] is registry.get(Place)
