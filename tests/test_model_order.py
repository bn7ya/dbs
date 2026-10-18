import random

import pytest
from django.db.models.signals import post_save

from dbs.engine import create_backup, restore_backup
from dbs.engine.restore import ordered_records
from tests.payloads import read_payload
from dbs.introspect import backup_plan, discover_models
from dbs.registry import BackupRegistry
from tests.conftest import FAST_KDF
from tests.format1 import as_format1
from tests.restoreapp.models import Bar, Pizzeria, Place, Restaurant, Venue

PASS = "model-order-pass-phrase"


def _registry(*models):
    registry = BackupRegistry()
    for model in models:
        registry.register(model)
    return registry


def _labels(records):
    return [record["model"] for record in records]


def _wipe_places():
    Pizzeria.objects.all().delete()
    Bar.objects.all().delete()
    Restaurant.objects.all().delete()
    Place.objects.all().delete()


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
def test_a_child_only_backup_restores_into_an_empty_database():
    diner = Restaurant.objects.create(name="diner", serves_pizza=True)
    container = create_backup(PASS, registry=_registry(Restaurant), kdf_params=FAST_KDF)
    _wipe_places()

    restore_backup(container, PASS, registry=_registry(Restaurant))

    restored = Restaurant.objects.get(pk=diner.pk)
    assert restored.name == "diner"
    assert restored.serves_pizza


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


@pytest.mark.django_db
def test_restore_loads_in_the_recorded_order_whatever_order_the_records_arrive_in():
    for index in range(3):
        Pizzeria.objects.create(name=f"slice {index}")
    registry = _registry(Pizzeria)

    def shuffled(document, records, files):
        records = list(records)
        random.Random(7).shuffle(records)
        records.reverse()
        return document, records, files

    container = as_format1(
        create_backup(PASS, registry=registry, kdf_params=FAST_KDF), PASS, edit=shuffled
    )
    _wipe_places()
    saved = []

    def note(sender, **kwargs):
        saved.append(sender._meta.label_lower)

    post_save.connect(note)
    try:
        restore_backup(container, PASS, registry=registry)
    finally:
        post_save.disconnect(note)

    first_seen = list(dict.fromkeys(saved))
    assert first_seen == ["restoreapp.place", "restoreapp.restaurant", "restoreapp.pizzeria"]
    assert saved == sorted(saved, key=first_seen.index)
    assert Pizzeria.objects.count() == 3


def test_a_backup_without_a_recorded_order_loads_parents_first():
    records = [
        {"model": "restoreapp.pizzeria", "pk": 1, "fields": {}},
        {"model": "restoreapp.restaurant", "pk": 1, "fields": {}},
        {"model": "restoreapp.place", "pk": 1, "fields": {}},
    ]

    assert _labels(ordered_records({}, records)) == [
        "restoreapp.place",
        "restoreapp.restaurant",
        "restoreapp.pizzeria",
    ]


def test_the_plan_keeps_a_registered_parents_own_configuration():
    registry = _registry(Place, Restaurant)

    configs = dict(backup_plan(registry))

    assert configs[Place] is registry.get(Place)
