from __future__ import annotations

import json

from django.core import serializers
from django.core.management.color import no_style
from django.db import connections, transaction


def serialize_model(model, config, excluded: set[str]) -> list[dict]:
    queryset = config.get_queryset(model).order_by("pk")
    payload = serializers.serialize(
        "json", queryset.iterator(), use_natural_foreign_keys=False
    )
    records = json.loads(payload)
    if excluded:
        for record in records:
            for name in excluded:
                record.get("fields", {}).pop(name, None)
    return records


def reset_sequences(connection, models) -> None:
    if not models:
        return
    ordered = sorted(models, key=lambda model: model._meta.label)
    statements = connection.ops.sequence_reset_sql(no_style(), ordered)
    if not statements:
        return
    with connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)


def load_records(records: list[dict], *, using: str = "default") -> int:
    if not records:
        return 0
    connection = connections[using]
    saved = 0
    restored_models = set()
    with transaction.atomic(using=using):
        with connection.constraint_checks_disabled():
            for obj in serializers.deserialize(
                "json", json.dumps(records), using=using, ignorenonexistent=True
            ):
                obj.save(using=using)
                restored_models.add(type(obj.object))
                saved += 1
        connection.check_constraints()
        reset_sequences(connection, restored_models)
    return saved
