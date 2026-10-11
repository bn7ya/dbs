from __future__ import annotations

import json
import logging

from django.apps import apps
from django.core import serializers
from django.core.exceptions import FieldDoesNotExist, ObjectDoesNotExist
from django.core.management.color import no_style
from django.core.serializers.json import Serializer as JSONSerializer
from django.db import connections, transaction

from .exceptions import RestoreError

logger = logging.getLogger("dbs")


def has_natural_key(model) -> bool:
    return hasattr(model, "natural_key") and hasattr(
        model._default_manager, "get_by_natural_key"
    )


class AllRowsSerializer(JSONSerializer):
    def __init__(self, carried=frozenset()):
        super().__init__()
        self.carried = carried
        self.natural_keys: dict = {}

    def by_natural_key(self, model) -> bool:
        return model not in self.carried and has_natural_key(model)

    def natural_key_of(self, model, column, value, database):
        key = (model, column, value)
        if key not in self.natural_keys:
            row = model._base_manager.using(database).get(**{column: value})
            self.natural_keys[key] = list(row.natural_key())
        return self.natural_keys[key]

    def handle_fk_field(self, obj, field):
        target = field.remote_field.model
        if not self.by_natural_key(target):
            return super().handle_fk_field(obj, field)
        value = getattr(obj, field.attname)
        self._current[field.name] = (
            None
            if value is None
            else self.natural_key_of(target, field.target_field.attname, value, obj._state.db)
        )

    def handle_m2m_field(self, obj, field):
        through = field.remote_field.through
        if not through._meta.auto_created:
            return
        target_ids = through._base_manager.using(obj._state.db).filter(
            **{field.m2m_field_name(): obj.pk}
        ).values(field.m2m_reverse_field_name())
        related = (
            field.related_model._base_manager.using(obj._state.db)
            .filter(pk__in=target_ids)
            .order_by("pk")
            .only("pk")
        )
        if self.by_natural_key(field.related_model):
            self._current[field.name] = [
                self.natural_key_of(field.related_model, "pk", item.pk, obj._state.db)
                for item in related
            ]
            return
        self._current[field.name] = [
            self._value_from_field(item, item._meta.pk) for item in related
        ]


def serialize_model(model, config, excluded: set[str], carried=frozenset()) -> list[dict]:
    queryset = config.get_queryset(model).order_by("pk")
    payload = AllRowsSerializer(carried).serialize(
        queryset.iterator(), use_natural_foreign_keys=False
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


class NaturalKeyResolver:
    def __init__(self, records: list[dict], using: str):
        self.using = using
        self.carried = {record.get("model") for record in records}
        self.resolved: dict = {}
        self.dropped: dict[str, list[str]] = {}
        self.by_id: set[str] = set()

    def lookup(self, model, key):
        cache_key = (model, tuple(json.dumps(part) for part in key))
        if cache_key not in self.resolved:
            manager = model._default_manager.db_manager(self.using)
            try:
                self.resolved[cache_key] = manager.get_by_natural_key(*key)
            except ObjectDoesNotExist:
                self.resolved[cache_key] = None
        return self.resolved[cache_key]

    def foreign_key(self, record, field, key):
        target = self.lookup(field.related_model, key)
        if target is None:
            raise RestoreError(
                f"{record['model']} {record.get('pk')!r} refers through {field.name!r} to "
                f"{field.related_model._meta.label_lower} {_describe(key)}, which this "
                "database does not have. Create it, or migrate this database to the "
                "same code as the backup, and restore again."
            )
        return getattr(target, field.target_field.attname)

    def members(self, field, values):
        resolved = []
        for value in values:
            if not isinstance(value, list):
                self.note_id_reference(field.related_model)
                resolved.append(value)
                continue
            target = self.lookup(field.related_model, value)
            if target is None:
                label = field.related_model._meta.label_lower
                self.dropped.setdefault(label, []).append(_describe(value))
                continue
            resolved.append(target.pk)
        return resolved

    def note_id_reference(self, model):
        label = model._meta.label_lower
        if label not in self.carried and has_natural_key(model):
            self.by_id.add(label)

    def record(self, record: dict) -> dict:
        try:
            model = apps.get_model(record["model"])
        except (KeyError, LookupError):
            return record
        fields = dict(record.get("fields", {}))
        for name, value in record.get("fields", {}).items():
            try:
                field = model._meta.get_field(name)
            except FieldDoesNotExist:
                continue
            if not field.is_relation or value is None:
                continue
            if field.many_to_many and isinstance(value, list):
                fields[name] = self.members(field, value)
            elif isinstance(value, list):
                fields[name] = self.foreign_key(record, field, value)
            else:
                self.note_id_reference(field.related_model)
        return {**record, "fields": fields}

    def report(self) -> None:
        for label, keys in sorted(self.dropped.items()):
            logger.warning(
                "restore left out %d reference(s) to %s that this database does not have: %s",
                len(keys),
                label,
                ", ".join(sorted(set(keys))),
            )
        if self.by_id:
            logger.warning(
                "this backup refers to %s by id, and those rows are not in the backup; "
                "if this database numbered them differently, check those references "
                "after the restore (a backup taken with this version of DBS refers to "
                "them by natural key instead)",
                ", ".join(sorted(self.by_id)),
            )


def _describe(key) -> str:
    return ".".join(str(part) for part in key)


def resolve_natural_keys(records: list[dict], using: str) -> list[dict]:
    resolver = NaturalKeyResolver(records, using)
    resolved = [resolver.record(record) for record in records]
    resolver.report()
    return resolved


def load_records(records: list[dict], *, using: str = "default") -> int:
    if not records:
        return 0
    connection = connections[using]
    saved = 0
    restored_models = set()
    with transaction.atomic(using=using):
        records = resolve_natural_keys(records, using)
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
