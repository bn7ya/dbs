from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import django
from django.apps import apps
from django.core.exceptions import FieldDoesNotExist
from django.db import models

from ..exceptions import RestoreError
from ..introspect import config_for, excluded_fields
from ..notices import (
    DJANGO_VERSION,
    FIELDS_LEFT_OUT,
    FIELDS_NOT_IN_BACKUP,
    FILES_LEFT_OUT,
    MIGRATIONS_DIFFER,
    MODELS_LEFT_OUT,
    RestoreWarning,
)
from ..registry import backup_registry
from ..serialize import carried_fields, serialized_fields
from .backup import applied_migrations, migration_state

LISTED_MIGRATIONS = 10


@dataclass
class SchemaGaps:
    missing_tables: list = field(default_factory=list)
    missing_rows: Counter = field(default_factory=Counter)
    missing_files: Counter = field(default_factory=Counter)
    fields_left_out: dict = field(default_factory=dict)
    fields_not_in_backup: dict = field(default_factory=dict)
    files_left_out: Counter = field(default_factory=Counter)

    @property
    def missing_models(self) -> list[str]:
        return sorted(set(self.missing_rows) | set(self.missing_files))

    def leaves_out(self, entry) -> bool:
        if entry.kind != "storage":
            return False
        return (
            entry.model in self.missing_files
            or f"{entry.model}.{entry.field}" in self.files_left_out
        )


def installed_model(label):
    if not label:
        return None
    try:
        model = apps.get_model(label)
    except (LookupError, ValueError):
        return None
    return None if model._meta.swapped else model


def compare_schema(records: list, files: list, labels, connection) -> SchemaGaps:
    gaps = SchemaGaps()
    rows = Counter(record.get("model") for record in records)
    carried = carried_fields(records)
    tables = {
        name.casefold()
        for name in connection.introspection.table_names(include_views=True)
    }
    for label in sorted(set(rows) | set(labels)):
        model = installed_model(label)
        if model is None:
            if rows[label]:
                gaps.missing_rows[label] = rows[label]
            continue
        if model._meta.db_table.casefold() not in tables:
            gaps.missing_tables.append(label)
            continue
        if not rows[label]:
            continue
        known = {each.name for each in model._meta.get_fields()}
        left_out = sorted(carried[label] - known)
        if left_out:
            gaps.fields_left_out[label] = left_out
        excluded = excluded_fields(model, config_for(backup_registry, model))
        not_in_backup = sorted(
            each.name
            for each in serialized_fields(model)
            if each.name not in carried[label] and each.name not in excluded
        )
        if not_in_backup:
            gaps.fields_not_in_backup[label] = not_in_backup
    for entry, _data in files:
        if entry.kind != "storage":
            continue
        model = installed_model(entry.model)
        if model is None:
            gaps.missing_files[entry.model] += 1
        elif not _is_file_field(model, entry.field):
            gaps.files_left_out[f"{entry.model}.{entry.field}"] += 1
    return gaps


def _is_file_field(model, name) -> bool:
    try:
        return isinstance(model._meta.get_field(name), models.FileField)
    except FieldDoesNotExist:
        return False


def refuse_gaps(gaps: SchemaGaps, *, allow_missing_models: bool) -> None:
    if gaps.missing_tables:
        raise RestoreError(
            "This database has no table for "
            + ", ".join(gaps.missing_tables)
            + ". Run migrate, then restore again."
        )
    if gaps.missing_models and not allow_missing_models:
        raise RestoreError(
            "The backup holds data for models this project does not have: "
            + _held(gaps)
            + ". Install their apps, or deploy the code the backup was taken from, and "
            "restore again; or allow missing models to restore everything else without them."
        )


def schema_warnings(gaps: SchemaGaps, merging_into) -> list[RestoreWarning]:
    found = []
    if gaps.missing_models:
        found.append(
            RestoreWarning(
                MODELS_LEFT_OUT,
                f"Left out {_held(gaps)}, which this project does not have.",
            )
        )
    for label, names in gaps.fields_left_out.items():
        found.append(
            RestoreWarning(
                FIELDS_LEFT_OUT,
                f"{label}: {', '.join(names)} "
                + _agree(names, "is", "are")
                + " in the backup but not in this project's model, so "
                + _agree(names, "its values are", "their values are")
                + " left out.",
            )
        )
    for label, names in gaps.fields_not_in_backup.items():
        default = _agree(names, "its default", "their defaults")
        outcome = (
            f"Rows new to this database get {default}; rows already here keep their values."
            if label in merging_into
            else f"Restored rows get {default}."
        )
        found.append(
            RestoreWarning(
                FIELDS_NOT_IN_BACKUP,
                f"{label}: {', '.join(names)} "
                + _agree(names, "is", "are")
                + f" not in the backup. {outcome}",
            )
        )
    for target, count in sorted(gaps.files_left_out.items()):
        found.append(
            RestoreWarning(
                FILES_LEFT_OUT,
                f"Left out {_count(count, 'file')} of {target}: this project's model has "
                "no file field by that name.",
            )
        )
    return found


def _held(gaps: SchemaGaps) -> str:
    described = []
    for label in gaps.missing_models:
        counts = [
            _count(gaps.missing_rows[label], "row"),
            _count(gaps.missing_files[label], "file"),
        ]
        described.append(f"{label} ({', '.join(count for count in counts if count)})")
    return ", ".join(described)


def _count(number: int, noun: str) -> str:
    if not number:
        return ""
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def _agree(names, one: str, many: str) -> str:
    return one if len(names) == 1 else many


def migration_warnings(document: dict, connection) -> list[RestoreWarning]:
    found = []
    backup_django = document.get("django_version")
    if backup_django and backup_django != django.get_version():
        found.append(
            RestoreWarning(
                DJANGO_VERSION,
                f"The backup was taken with Django {backup_django}; this project runs "
                f"Django {django.get_version()}.",
            )
        )
    if document.get("applied_migrations") is not None:
        difference = _applied_difference(
            document["applied_migrations"], applied_migrations(connection)
        )
    elif document.get("migrations") is not None:
        difference = _latest_difference(document["migrations"], migration_state(connection))
    else:
        difference = ""
    if difference:
        found.append(RestoreWarning(MIGRATIONS_DIFFER, difference))
    return found


def _applied_difference(recorded: dict, here: dict) -> str:
    there = {f"{app}.{name}" for app, names in recorded.items() for name in names}
    ours = {f"{app}.{name}" for app, names in here.items() for name in names}
    parts = []
    if there - ours:
        parts.append("Not applied here: " + _listed(there - ours) + ".")
    if ours - there:
        parts.append("Applied here only: " + _listed(ours - there) + ".")
    if not parts:
        return ""
    return "Migrations differ from the database the backup was taken from. " + " ".join(parts)


def _latest_difference(recorded: dict, here: dict) -> str:
    differing = [
        f"{app} (backup at {recorded.get(app) or 'none'}, here at {here.get(app) or 'none'})"
        for app in sorted(set(recorded) | set(here))
        if recorded.get(app) != here.get(app)
    ]
    if not differing:
        return ""
    return (
        "Migrations differ from the database the backup was taken from: "
        + ", ".join(differing)
        + "."
    )


def _listed(names) -> str:
    ordered = sorted(names)
    shown = ", ".join(ordered[:LISTED_MIGRATIONS])
    hidden = len(ordered) - LISTED_MIGRATIONS
    return f"{shown} and {hidden} more" if hidden > 0 else shown
