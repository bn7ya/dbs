"""Model / field / relation discovery.

Decides *which* models go into a backup, *which* of their fields carry files,
and *what order* to restore them in so foreign keys resolve.
"""

from __future__ import annotations

from django.apps import apps
from django.conf import settings
from django.db import models

from .registry import BackupRegistry, FieldType, ModelBackup

# Bookkeeping tables that are normally recreated by migrations and whose primary
# keys are not stable across environments. Excluded by default; override with the
# ``DBS_EXCLUDE_MODELS`` setting (a list of ``"app_label.ModelName"`` strings).
DEFAULT_EXCLUDES = {
    "contenttypes.contenttype",
    "auth.permission",
    "admin.logentry",
    "sessions.session",
}


def _label(model) -> str:
    return f"{model._meta.app_label}.{model._meta.model_name}"


def _excluded_labels() -> set[str]:
    configured = getattr(settings, "DBS_EXCLUDE_MODELS", None)
    if configured is None:
        return set(DEFAULT_EXCLUDES)
    return {label.lower() for label in configured}


def discover_models(registry: BackupRegistry) -> list[type]:
    """Return the concrete models to back up.

    If anything is registered, that explicit set wins. Otherwise every concrete,
    non-excluded model from the installed apps is included.
    """
    if not registry.is_empty():
        chosen = registry.models()
    else:
        excluded = _excluded_labels()
        chosen = [
            model
            for model in apps.get_models()
            if not model._meta.proxy
            and not model._meta.abstract
            and _label(model) not in excluded
        ]
    return topological_order(chosen)


def config_for(registry: BackupRegistry, model) -> ModelBackup:
    return registry.get(model) or ModelBackup()


def field_types(model, config: ModelBackup) -> dict[str, FieldType]:
    """Return ``field_name -> FieldType`` for the fields that need special handling.

    Only FILE / FILE_PATH / EXCLUDE fields are returned; everything else is an
    ordinary value handled by the serializer.
    """
    overrides = {name: ftype for name, ftype in (config.overrides or {}).items()}
    result: dict[str, FieldType] = {}
    for field in model._meta.get_fields():
        name = getattr(field, "name", None)
        if name is None:
            continue
        if name in overrides:
            result[name] = overrides[name]
        elif isinstance(field, models.FileField):
            result[name] = FieldType.FILE
    # Honour overrides for fields that are not Django relations/files (e.g. a
    # CharField marked FILE_PATH or any field marked EXCLUDE).
    for name, ftype in overrides.items():
        result[name] = ftype
    return result


def file_fields(model, config: ModelBackup) -> dict[str, FieldType]:
    """Subset of :func:`field_types` that actually carry file bytes."""
    return {
        name: ftype
        for name, ftype in field_types(model, config).items()
        if ftype in (FieldType.FILE, FieldType.FILE_PATH)
    }


def excluded_fields(model, config: ModelBackup) -> set[str]:
    return {
        name
        for name, ftype in field_types(model, config).items()
        if ftype is FieldType.EXCLUDE
    }


def topological_order(model_list: list[type]) -> list[type]:
    """Order models so a model's foreign-key targets come before it.

    Falls back to the original order for any models caught in a dependency cycle
    (self-references and circular FKs); the restore path disables FK enforcement
    so those still load correctly.
    """
    model_set = set(model_list)
    deps: dict[type, set] = {m: set() for m in model_list}
    for model in model_list:
        for field in model._meta.get_fields():
            if (
                field.is_relation
                and getattr(field, "concrete", False)
                and not field.many_to_many
                and field.related_model in model_set
                and field.related_model is not model
            ):
                deps[model].add(field.related_model)

    ordered: list[type] = []
    resolved: set = set()
    remaining = list(model_list)
    while remaining:
        progressed = False
        for model in list(remaining):
            if deps[model] <= resolved:
                ordered.append(model)
                resolved.add(model)
                remaining.remove(model)
                progressed = True
        if not progressed:  # cycle -> emit the rest in their given order
            ordered.extend(remaining)
            break
    return ordered
