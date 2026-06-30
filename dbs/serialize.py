"""Turning model instances into records and back, on top of Django's serializers.

We deliberately reuse ``django.core.serializers`` so foreign keys, many-to-many
relations and field (de)serialization behave exactly like ``dumpdata`` /
``loaddata`` -- we only layer on per-field exclusion and dependency ordering.

The ``json`` serializer is used so every record is already JSON-safe and can be
embedded directly in the payload document.
"""

from __future__ import annotations

import json

from django.core import serializers
from django.db import connections


def serialize_model(model, config, excluded: set[str]) -> list[dict]:
    """Serialize all (configured) instances of ``model`` to JSON-safe dicts."""
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
    """Deserialize and save ``records``, preserving primary keys.

    Records are expected to already be in foreign-key dependency order. FK
    enforcement is deferred for the duration so cyclic / unordered references
    still load, mirroring how ``loaddata`` behaves; the deferred constraints are
    re-checked afterwards so a genuinely broken backup is still reported.
    """
    if not records:
        return 0
    connection = connections[using]
    saved = 0
    with connection.constraint_checks_disabled():
        for obj in serializers.deserialize(
            "json", json.dumps(records), using=using, ignorenonexistent=True
        ):
            obj.save(using=using)
            saved += 1
    connection.check_constraints()
    return saved
