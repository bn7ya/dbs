from __future__ import annotations

import base64
import binascii
import json
import logging
import re
import secrets

from django.apps import apps
from django.core import serializers
from django.core.exceptions import FieldDoesNotExist, ObjectDoesNotExist, ValidationError
from django.core.management.color import no_style
from django.core.serializers.json import DjangoJSONEncoder
from django.core.serializers.python import Serializer as PythonSerializer
from django.db import connections, models, transaction
from django.db.models import AutoField, Model

from .exceptions import BackupError, RestoreError

logger = logging.getLogger("dbs")

EXISTENCE_BATCH = 500

RECORD_BATCH_ROWS = 500

RECORD_BATCH_BYTES = 8 * 1024 * 1024

FETCH_BYTES_TARGET = 16 * 1024 * 1024

SPLICED_VALUE_BYTES = 1024 * 1024

NATURAL_KEY_CACHE = 10000

HEAVY_FIELDS = (models.BinaryField, models.TextField, models.JSONField)

NEEDS_ESCAPING = re.compile(r'["\\\x00-\x1f]')


class RawBytes:
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value


def has_natural_key(model) -> bool:
    return hasattr(model, "natural_key") and hasattr(
        model._default_manager, "get_by_natural_key"
    )


class AllRowsSerializer(PythonSerializer):
    def __init__(self, carried=frozenset(), excluded=frozenset()):
        super().__init__()
        self.carried = carried
        self.excluded = excluded
        self.natural_keys: dict = {}
        self.members: dict = {}

    def prepare(self, objects: list) -> None:
        self.members = {}
        if not objects:
            return
        database = objects[0]._state.db
        keys = [obj.pk for obj in objects]
        for field in objects[0]._meta.concrete_model._meta.local_many_to_many:
            if (
                field.serialize
                and field.remote_field.through._meta.auto_created
                and field.name not in self.excluded
            ):
                self.members[field.name] = self._members_of(field, keys, database)

    def _members_of(self, field, keys: list, database) -> dict:
        source, target = field.m2m_field_name(), field.m2m_reverse_field_name()
        links = field.remote_field.through._base_manager.using(database).filter(
            **{f"{source}__in": keys}
        )
        related = (
            field.related_model._base_manager.using(database)
            .filter(pk__in=links.values(target))
            .order_by("pk")
            .only("pk")
        )
        natural = self.by_natural_key(field.related_model)
        values = {
            item.pk: (
                self.natural_key_of(field.related_model, "pk", item.pk, database)
                if natural
                else self._value_from_field(item, item._meta.pk)
            )
            for item in related
        }
        rank = {key: position for position, key in enumerate(values)}
        grouped: dict = {}
        for owner, member in links.values_list(source, target):
            if member in rank:
                grouped.setdefault(owner, set()).add(member)
        return {
            owner: [values[member] for member in sorted(members, key=rank.__getitem__)]
            for owner, members in grouped.items()
        }

    def get_dump_object(self, obj):
        for name in self.excluded:
            self._current.pop(name, None)
        return super().get_dump_object(obj)

    def by_natural_key(self, model) -> bool:
        return model not in self.carried and has_natural_key(model)

    def natural_key_of(self, model, column, value, database):
        key = (model, column, value)
        if key not in self.natural_keys:
            if len(self.natural_keys) >= NATURAL_KEY_CACHE:
                self.natural_keys.clear()
            row = model._base_manager.using(database).get(**{column: value})
            self.natural_keys[key] = list(row.natural_key())
        return self.natural_keys[key]

    def handle_field(self, obj, field):
        if field.name in self.excluded:
            return
        if isinstance(field, models.BinaryField):
            raw = field.value_from_object(obj)
            if raw is not None and len(raw) >= SPLICED_VALUE_BYTES:
                self._current[field.name] = RawBytes(raw)
                return
        super().handle_field(obj, field)

    def encoded(self, objects: list) -> list:
        return [
            encode_record(record)
            for record in self.serialize(objects, use_natural_foreign_keys=False)
        ]

    def handle_fk_field(self, obj, field):
        if field.name in self.excluded:
            return
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
        if not through._meta.auto_created or field.name in self.excluded:
            return
        prefetched = self.members.get(field.name)
        if prefetched is not None:
            self._current[field.name] = prefetched.get(obj.pk, [])
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


def encode_record(record: dict) -> list:
    fields = record["fields"]
    spliced = {name: value for name, value in fields.items() if _spliced(value)}
    if not spliced:
        return [_dumps(record)]
    tokens = {name: f"dbs-spliced-{secrets.token_hex(16)}" for name in spliced}
    text = json.dumps(
        {**record, "fields": {**fields, **tokens}}, cls=DjangoJSONEncoder, ensure_ascii=False
    )
    pieces = []
    for name, value in spliced.items():
        before, _, text = text.partition(json.dumps(tokens[name]))
        pieces.append(before.encode("utf-8"))
        pieces.extend(_json_string(value))
    pieces.append(text.encode("utf-8"))
    return pieces


def _dumps(value) -> bytes:
    return json.dumps(value, cls=DjangoJSONEncoder, ensure_ascii=False).encode("utf-8")


def _spliced(value) -> bool:
    return isinstance(value, RawBytes) or (
        isinstance(value, str) and len(value) >= SPLICED_VALUE_BYTES
    )


def _json_string(value) -> list:
    if isinstance(value, RawBytes):
        return [b'"', base64.b64encode(value.value), b'"']
    if NEEDS_ESCAPING.search(value) is None:
        return [b'"', value.encode("utf-8"), b'"']
    return [json.dumps(value, ensure_ascii=False).encode("utf-8")]


def decode_large_binaries(records: list) -> None:
    for record in records:
        fields = record.get("fields")
        if not isinstance(fields, dict):
            continue
        large = [
            name
            for name, value in fields.items()
            if isinstance(value, str) and len(value) >= SPLICED_VALUE_BYTES
        ]
        if not large:
            continue
        try:
            model = apps.get_model(record["model"])
        except (KeyError, LookupError, ValueError):
            continue
        for name in large:
            try:
                field = model._meta.get_field(name)
            except FieldDoesNotExist:
                continue
            if isinstance(field, models.BinaryField):
                try:
                    fields[name] = binascii.a2b_base64(fields[name])
                except (binascii.Error, ValueError) as exc:
                    raise RestoreError(
                        f"{record['model']} {record.get('pk')!r} holds a {name} that is not "
                        f"base64: {exc}"
                    ) from exc


def record_size(pieces: list) -> int:
    return sum(len(piece) for piece in pieces)


def framed_records(batch: list) -> list:
    pieces: list = []
    small: list = [b"["]
    for index, record in enumerate(batch):
        if index:
            small.append(b",")
        for piece in record:
            if len(piece) < SPLICED_VALUE_BYTES:
                small.append(piece)
                continue
            pieces.append(b"".join(small))
            pieces.append(piece)
            small = []
    small.append(b"]")
    pieces.append(b"".join(small))
    return [piece for piece in pieces if piece]


def has_heavy_fields(model) -> bool:
    return any(isinstance(field, HEAVY_FIELDS) for field in model._meta.concrete_fields)


def keyset_pageable(queryset) -> bool:
    composite = getattr(models, "CompositePrimaryKey", None)
    return not queryset.query.is_sliced and not (
        composite is not None and isinstance(queryset.model._meta.pk, composite)
    )


class Pages:
    def __init__(self, queryset, rows: int, *, adaptive: bool = True):
        self.rows = rows
        self.keyset = keyset_pageable(queryset)
        self.queryset = queryset.order_by("pk") if not queryset.query.is_sliced else queryset
        self.size = 1 if adaptive and has_heavy_fields(queryset.model) else rows

    def measured(self, encoded_bytes: int, count: int) -> None:
        mean = max(1, encoded_bytes // max(1, count))
        self.size = max(1, min(self.rows, self.size * 2, FETCH_BYTES_TARGET // mean))

    def __iter__(self):
        if not self.keyset:
            yield from self._iterated()
            return
        last = None
        while True:
            size = self.size
            page = self.queryset if last is None else self.queryset.filter(pk__gt=last)
            chunk = list(page[:size])
            if not chunk:
                return
            yield chunk
            if len(chunk) < size:
                return
            last = chunk[-1].pk

    def _iterated(self):
        chunk: list = []
        for instance in self.queryset.iterator(chunk_size=self.rows):
            chunk.append(instance)
            if len(chunk) >= self.size:
                yield chunk
                chunk = []
        if chunk:
            yield chunk


def serialize_batches(
    model, config, excluded: set[str], carried=frozenset(), using: str | None = None,
    *, rows: int = RECORD_BATCH_ROWS, limit: int | None = None,
    budget: int = RECORD_BATCH_BYTES,
):
    queryset = config.get_queryset(model)
    if using is not None:
        queryset = queryset.using(using)
    serializer = AllRowsSerializer(carried, frozenset(excluded))
    pages = Pages(queryset, rows)
    ceiling = budget if limit is None else min(budget, limit)
    batch: list = []
    size = 0
    for chunk in pages:
        serializer.prepare(chunk)
        encoded = serializer.encoded(chunk)
        pages.measured(sum(record_size(pieces) for pieces in encoded), len(chunk))
        for instance, pieces in zip(chunk, encoded):
            length = record_size(pieces)
            if limit is not None and length + 2 > limit:
                raise BackupError(
                    f"{instance._meta.label_lower} {instance.pk!r} serializes to "
                    f"{length + 2} bytes, above the {limit} byte limit for one row."
                )
            if batch and (size + length + len(batch) + 2 > ceiling or len(batch) >= rows):
                yield framed_records(batch), len(batch)
                batch, size = [], 0
            batch.append(pieces)
            size += length
    if batch:
        yield framed_records(batch), len(batch)


def raise_sequences(connection, models) -> None:
    if not models:
        return
    ordered = sorted(models, key=lambda model: model._meta.label)
    if connection.vendor == "postgresql":
        _raise_postgresql_sequences(connection, ordered)
        return
    statements = connection.ops.sequence_reset_sql(no_style(), ordered)
    if not statements:
        return
    with connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)


def _auto_field(model):
    return next(
        (field for field in model._meta.local_fields if isinstance(field, AutoField)),
        None,
    )


def _raise_postgresql_sequences(connection, models) -> None:
    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        for model in models:
            field = _auto_field(model)
            if field is None:
                continue
            table = quote(model._meta.db_table)
            cursor.execute("SELECT pg_get_serial_sequence(%s, %s)", [table, field.column])
            sequence = cursor.fetchone()[0]
            if sequence is None:
                continue
            cursor.execute(
                "SELECT setval(%s::regclass, highest.value) "
                f"FROM (SELECT max({quote(field.column)}) AS value FROM {table}) AS highest, "
                f"{sequence.replace('%', '%%')} AS counter "
                "WHERE highest.value >= CASE WHEN counter.is_called "
                "THEN counter.last_value + 1 ELSE counter.last_value END",
                [sequence],
            )


class NaturalKeyResolver:
    def __init__(self, records: list[dict], using: str, carried=None):
        self.using = using
        self.carried = (
            set(carried)
            if carried is not None
            else {record.get("model") for record in records}
        )
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


def existing_rows(records: list[dict], using: str) -> dict:
    wanted: dict = {}
    for record in records:
        try:
            model = apps.get_model(record["model"])
            wanted.setdefault(model, []).append(model._meta.pk.to_python(record["pk"]))
        except (KeyError, LookupError, ValidationError):
            continue
    found: dict = {}
    for model, keys in wanted.items():
        manager = model._base_manager.using(using)
        present = found.setdefault(model, set())
        for start in range(0, len(keys), EXISTENCE_BATCH):
            batch = keys[start : start + EXISTENCE_BATCH]
            present.update(manager.filter(pk__in=batch).values_list("pk", flat=True))
    return found


def _deserialized(record: dict, using: str):
    try:
        restored = serializers.deserialize(
            "python", [record], using=using, ignorenonexistent=True
        )
        return next(iter(restored), None)
    except Exception as exc:
        raise RestoreError(
            f"{record.get('model')} {record.get('pk')!r} could not be read: {exc}"
        ) from exc


def _carried_columns(model, names) -> list[str]:
    columns = []
    for name in names:
        try:
            field = model._meta.get_field(name)
        except FieldDoesNotExist:
            continue
        if field.concrete and not field.many_to_many and not field.primary_key:
            columns.append(field.name)
    return columns


def _update_carried_fields(restored, record: dict, using: str) -> None:
    instance = restored.object
    columns = _carried_columns(type(instance), record.get("fields", {}))
    if columns:
        Model.save_base(instance, using=using, raw=True, update_fields=columns)
    for accessor, members in (restored.m2m_data or {}).items():
        getattr(instance, accessor).set(members)


class RowLoader:
    def __init__(self, using: str):
        self.using = using
        self.connection = connections[using]
        self.saved = 0
        self.seen = 0
        self.models: set = set()

    def save(self, records: list[dict]) -> int:
        self.seen += len(records)
        existing = existing_rows(records, self.using)
        saved = 0
        for record in records:
            restored = _deserialized(record, self.using)
            if restored is None:
                continue
            model = type(restored.object)
            if restored.object.pk in existing.get(model, ()):
                _update_carried_fields(restored, record, self.using)
            else:
                restored.save(using=self.using)
            self.models.add(model)
            saved += 1
        self.saved += saved
        return saved

    def finish(self, *, adjust_sequences: bool = True) -> int:
        self.connection.check_constraints()
        if not self.seen:
            return 0
        if adjust_sequences:
            raise_sequences(self.connection, self.models)
        return self.saved


def save_records(records: list[dict], *, using: str, adjust_sequences: bool = True) -> int:
    loader = RowLoader(using)
    with loader.connection.constraint_checks_disabled():
        loader.save(records)
    return loader.finish(adjust_sequences=adjust_sequences)


def load_records(
    records: list[dict], *, using: str = "default", adjust_sequences: bool = True
) -> int:
    if not records:
        return 0
    records = resolve_natural_keys(records, using)
    with transaction.atomic(using=using):
        return save_records(records, using=using, adjust_sequences=adjust_sequences)
