from __future__ import annotations

import json

from django.core import serializers
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


def load_records(records: list[dict], *, using: str = "default") -> int:
    if not records:
        return 0
    connection = connections[using]
    saved = 0
    with transaction.atomic(using=using):
        with connection.constraint_checks_disabled():
            for obj in serializers.deserialize(
                "json", json.dumps(records), using=using, ignorenonexistent=True
            ):
                obj.save(using=using)
                saved += 1
        connection.check_constraints()
    return saved
