from __future__ import annotations

import hashlib
import json
import logging
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field

from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.db import models, router, transaction
from django.db.migrations.exceptions import BadMigrationError, CircularDependencyError
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.operations import RunSQL, SeparateDatabaseAndState
from django.db.migrations.recorder import MigrationRecorder
from django.db.migrations.state import ProjectState

from .. import transactions
from ..exceptions import RestoreError
from ..introspect import _configured_exclusions, topological_order
from ..serialize import raise_sequences

logger = logging.getLogger("dbs")

OWN_APP = "dbs"
REBUILT_VENDORS = ("sqlite", "postgresql", "mysql")
FOREIGN_KEY_SUFFIX = "_fk_%(to_table)s_%(to_column)s"
NAMED = 8


def label(model) -> str:
    return model._meta.label_lower


def named(items) -> str:
    items = list(items)
    more = f" and {len(items) - NAMED} more" if len(items) > NAMED else ""
    return ", ".join(str(item) for item in items[:NAMED]) + more


def migration_name(key) -> str:
    return f"{key[0]}.{key[1]}"


@dataclass
class Snapshot:
    state: ProjectState
    applied: list
    models: list
    unknown: list = field(default_factory=list)
    raw_sql: list = field(default_factory=list)

    @property
    def carried(self) -> list:
        excluded = explicit_exclusions()
        return [model for model in self.models if label(model) not in excluded]


def explicit_exclusions() -> set:
    return {entry for entry in _configured_exclusions() if not entry.startswith("-")}


@transactions.reads_connection
def applied_rows(connection) -> list:
    recorder = MigrationRecorder(connection)
    if not recorder.has_table():
        return []
    return sorted(recorder.applied_migrations())


def has_applied_migrations(connection) -> bool:
    return bool(applied_rows(connection))


@transactions.reads_connection
def snapshot(connection) -> Snapshot:
    executor = MigrationExecutor(connection)
    loader = executor.loader
    applied = {
        loader.graph.nodes[key] for key in loader.applied_migrations if key in loader.graph.nodes
    }
    state = ProjectState(real_apps=loader.unmigrated_apps)
    raw_sql = []
    for migration, _backwards in executor.migration_plan(
        loader.graph.leaf_nodes(), clean_start=True
    ):
        if migration not in applied:
            continue
        migration.mutate_state(state, preserve=False)
        if migration.app_label != OWN_APP and runs_raw_sql(migration):
            raw_sql.append(f"{migration.app_label}.{migration.name}")
    replaced = {key for migration in loader.replacements.values() for key in migration.replaces}
    unknown = sorted(
        key
        for key in loader.applied_migrations
        if key[0] in loader.migrated_apps
        and key[0] != OWN_APP
        and key not in loader.graph.nodes
        and key not in replaced
    )
    return Snapshot(
        state=state,
        applied=sorted(key for key in loader.applied_migrations),
        models=rebuildable(state, loader, connection),
        unknown=unknown,
        raw_sql=raw_sql,
    )


@transactions.reads_connection
def newest_tables(connection) -> set:
    loader = MigrationExecutor(connection).loader
    return {
        table
        for model in rebuildable(loader.project_state(), loader, connection)
        for table in tables_of(model)
    }


def runs_raw_sql(migration) -> bool:
    return any(
        isinstance(operation, RunSQL)
        or (isinstance(operation, SeparateDatabaseAndState) and operation.database_operations)
        for operation in migration.operations
    )


def rebuildable(state, loader, connection) -> list:
    found = [
        model
        for model in state.apps.get_models()
        if model._meta.app_label != OWN_APP
        and model._meta.app_label in loader.migrated_apps
        and model._meta.can_migrate(connection)
        and router.allow_migrate_model(connection.alias, model)
    ]
    return topological_order(found)


@transactions.reads_connection
def unmigrated_models(connection) -> list:
    loader = MigrationExecutor(connection).loader
    from django.apps import apps

    return [
        model._meta.label_lower
        for model in apps.get_models()
        if model._meta.app_label in loader.unmigrated_apps
        and model._meta.managed
        and not model._meta.proxy
    ]


def tables_of(model) -> list:
    names = [model._meta.db_table]
    for many in model._meta.local_many_to_many:
        through = many.remote_field.through
        if through._meta.auto_created:
            names.append(through._meta.db_table)
    return names


def shape_of(model) -> list:
    columns = [
        [column.column, column.get_internal_type(), bool(column.null), bool(column.primary_key)]
        for column in model._meta.local_concrete_fields
    ]
    return [label(model), model._meta.db_table, columns, sorted(tables_of(model)[1:])]


def schema_digest(model_list) -> str:
    shapes = sorted(shape_of(model) for model in model_list)
    return hashlib.sha256(json.dumps(shapes).encode("utf-8")).hexdigest()


def rewrite_records(connection, applied) -> tuple:
    recorder = MigrationRecorder(connection)
    recorder.ensure_schema()
    wanted = {tuple(row) for row in applied if row[0] != OWN_APP}
    current = {key for key in recorder.applied_migrations() if key[0] != OWN_APP}
    unapplied = sorted(current - wanted)
    recorded = sorted(wanted - current)
    for app, name in unapplied:
        recorder.record_unapplied(app, name)
    for app, name in recorded:
        recorder.record_applied(app, name)
    return unapplied, recorded


def recorded_snapshot(connection, applied) -> Snapshot:
    using = connection.alias
    with transaction.atomic(using=using):
        rewrite_records(connection, applied)
        found = snapshot(connection)
        transaction.set_rollback(True, using=using)
    return found


@dataclass
class RebuildPlan:
    target: Snapshot
    applied: list
    carried: list
    drop: list
    left_alone: list
    unapplied: list
    recorded: list

    @property
    def created(self) -> set:
        return {table for model in self.carried for table in tables_of(model)}

    @property
    def tables(self) -> list:
        return sorted(self.created)


@transactions.atomically_on_connection
def plan_rebuild(connection, header: dict) -> RebuildPlan:
    if connection.vendor not in REBUILT_VENDORS:
        raise RestoreError(
            f"A checkpoint's tables are rebuilt on SQLite, PostgreSQL and MySQL, not on "
            f"{connection.vendor}. Restore its rows alone with schema=False (--no-schema)."
        )
    applied = [tuple(row) for row in header.get("applied") or []]
    current = snapshot(connection)
    try:
        target = recorded_snapshot(connection, applied)
    except (ValueError, LookupError, BadMigrationError, CircularDependencyError) as exc:
        raise RestoreError(
            "The migrations this checkpoint recorded do not fit together in this "
            f"project: {exc} Check out the code it was taken from and restore again, or "
            "restore its rows alone with schema=False (--no-schema)."
        ) from exc
    if target.unknown:
        raise RestoreError(
            "This checkpoint was taken with migrations this project no longer has: "
            f"{named(migration_name(key) for key in target.unknown)}. Check out the code "
            "that has them and restore again, or restore its rows alone with "
            "schema=False (--no-schema)."
        )
    described = {label(model): model for model in target.models}
    labels = list(header["order"])
    missing = [name for name in labels if name not in described]
    if missing:
        raise RestoreError(
            f"This checkpoint holds rows of {named(missing)}, which the migrations it "
            "recorded do not describe in this project. Check out the code it was taken "
            "from and restore again, or restore its rows alone with schema=False "
            "(--no-schema)."
        )
    carried = [described[name] for name in labels]
    if header.get("schema") and schema_digest(carried) != header["schema"]:
        raise RestoreError(
            "The migrations this checkpoint recorded no longer describe the tables it "
            "was taken from: one of them was edited since. Check out the code it was "
            "taken from and restore again, or restore its rows alone with schema=False "
            "(--no-schema)."
        )
    held = set(labels)
    now = {label(model): model for model in current.models}
    kept = [model for model in target.models if label(model) not in held]
    changed = [
        label(model)
        for model in kept
        if label(model) not in now or shape_of(now[label(model)]) != shape_of(model)
    ]
    if changed:
        raise RestoreError(
            f"This checkpoint holds no rows of {named(changed)} (left out by "
            "DBS_EXCLUDE_MODELS when it was taken), and their tables have changed "
            "since, so it cannot put them back. Restore its rows alone with "
            "schema=False (--no-schema)."
        )
    existing = set(connection.introspection.table_names())
    staying = {table for model in kept for table in tables_of(model)}
    known = {table for model in current.models for table in tables_of(model)}
    wanted = {table for model in carried for table in tables_of(model)}
    drop = sorted(((known | wanted | newest_tables(connection)) - staying) & existing)
    was = {key for key in current.applied if key[0] != OWN_APP}
    will = {key for key in applied if key[0] != OWN_APP}
    return RebuildPlan(
        target=target,
        applied=applied,
        carried=carried,
        drop=drop,
        left_alone=left_alone(current, set(drop), existing),
        unapplied=[migration_name(key) for key in sorted(was - will)],
        recorded=[migration_name(key) for key in sorted(will - was)],
    )


def left_alone(current: Snapshot, dropped: set, existing: set) -> list:
    found = []
    for model in current.state.apps.get_models(include_auto_created=True):
        meta = model._meta
        if meta.proxy or not meta.managed or meta.swapped:
            continue
        if meta.db_table in dropped or meta.db_table not in existing:
            continue
        found.append(model)
    return found


@contextmanager
def rebuilding(connection):
    if connection.vendor == "sqlite" and connection.in_atomic_block:
        raise RestoreError(
            "SQLite cannot rebuild tables inside a transaction; restore the checkpoint "
            "outside transaction.atomic()."
        )
    with ExitStack() as stack:
        stack.enter_context(connection.constraint_checks_disabled())
        if connection.features.can_rollback_ddl:
            stack.enter_context(transaction.atomic(using=connection.alias))
        yield stack.enter_context(connection.schema_editor(atomic=False))


def rebuild(connection, plan: RebuildPlan, load) -> int:
    with rebuilding(connection) as editor:
        for table in plan.drop:
            editor.execute(editor.sql_delete_table % {"table": editor.quote_name(table)})
        for model in plan.carried:
            editor.create_model(model)
        with transaction.atomic(using=connection.alias):
            loaded = load()
            rewrite_records(connection, plan.applied)
            relink(connection, editor, plan)
            raise_sequences(connection, plan.carried)
        check_constraints(connection)
    if not connection.features.can_rollback_ddl:
        check_constraints(connection)
    forget_cached_rows()
    return loaded


@transactions.reads_connection
def check_constraints(connection) -> None:
    connection.check_constraints()


def forget_cached_rows() -> None:
    from django.apps import apps

    if apps.is_installed("django.contrib.contenttypes"):
        from django.contrib.contenttypes.models import ContentType

        ContentType.objects.clear_cache()


def relink(connection, editor, plan: RebuildPlan) -> None:
    created = plan.created
    with connection.cursor() as cursor:
        for model in plan.left_alone:
            for column in model._meta.local_concrete_fields:
                if column.remote_field is None or not column.db_constraint:
                    continue
                parent = column.target_field.model._meta.db_table
                if parent not in created:
                    continue
                settle_dangling(connection, cursor, model, column, parent)
                if connection.features.supports_foreign_keys and not has_foreign_key(
                    connection, cursor, model._meta.db_table, column.column
                ):
                    editor.deferred_sql.append(
                        editor._create_fk_sql(model, column, FOREIGN_KEY_SUFFIX)
                    )


def settle_dangling(connection, cursor, model, column, parent: str) -> None:
    quote = connection.ops.quote_name
    table, name = quote(model._meta.db_table), quote(column.column)
    dangling = (
        f"{name} IS NOT NULL AND {name} NOT IN "
        f"(SELECT {quote(column.target_field.column)} FROM {quote(parent)})"
    )
    on_delete = column.remote_field.on_delete
    if on_delete is models.SET_NULL and column.null:
        cursor.execute(f"UPDATE {table} SET {name} = NULL WHERE {dangling}")
        return
    if on_delete is models.CASCADE:
        cursor.execute(f"DELETE FROM {table} WHERE {dangling}")
        return
    cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE {dangling}")
    count = cursor.fetchone()[0]
    if count:
        raise RestoreError(
            f"{count} row(s) of {label(model)} refer through {column.name!r} to rows "
            "this checkpoint does not hold, and may not lose them. Remove or repoint "
            "those rows and restore again."
        )


def has_foreign_key(connection, cursor, table: str, column: str) -> bool:
    constraints = connection.introspection.get_constraints(cursor, table)
    return any(
        details.get("foreign_key") and list(details.get("columns") or []) == [column]
        for details in constraints.values()
    )


class HistoricalRows:
    def __init__(self, state_apps, using: str):
        self.apps = state_apps
        self.using = using
        self.seen = 0
        self.saved = 0

    def model_of(self, record: dict):
        try:
            return self.apps.get_model(record["model"])
        except (KeyError, LookupError, ValueError):
            raise RestoreError(
                f"This checkpoint holds a row of {record.get('model')!r}, which the "
                "migrations it recorded do not describe."
            ) from None

    def build(self, record: dict) -> tuple:
        model = self.model_of(record)
        meta = model._meta
        values: dict = {}
        links: list = []
        try:
            if record.get("pk") is not None and not is_composite(meta.pk):
                values[meta.pk.attname] = meta.pk.to_python(record["pk"])
            for name, value in (record.get("fields") or {}).items():
                column = meta.get_field(name)
                if getattr(column, "generated", False):
                    continue
                if column.many_to_many:
                    links.append((column, value or []))
                elif column.remote_field is not None:
                    values[column.attname] = (
                        None if value is None else column.target_field.to_python(value)
                    )
                else:
                    values[column.attname] = column.to_python(value)
        except (FieldDoesNotExist, ValidationError, TypeError, ValueError) as exc:
            raise RestoreError(
                f"{record.get('model')} {record.get('pk')!r} could not be read: {exc}"
            ) from exc
        return model(**values), links

    def check(self, records: list) -> None:
        for record in records:
            self.build(record)
        self.seen += len(records)

    def save(self, records: list) -> None:
        for record in records:
            instance, links = self.build(record)
            models.Model.save_base(instance, using=self.using, raw=True, force_insert=True)
            for many, members in links:
                self.link(instance, many, members)
        self.seen += len(records)
        self.saved += len(records)

    def link(self, instance, many, members: list) -> None:
        through = many.remote_field.through
        if not through._meta.auto_created or not members:
            return
        source = through._meta.get_field(many.m2m_field_name()).attname
        target = through._meta.get_field(many.m2m_reverse_field_name()).attname
        key = many.related_model._meta.pk
        through._base_manager.using(self.using).bulk_create(
            [
                through(**{source: instance.pk, target: key.to_python(member)})
                for member in members
            ]
        )


def is_composite(key) -> bool:
    composite = getattr(models, "CompositePrimaryKey", None)
    return composite is not None and isinstance(key, composite)
