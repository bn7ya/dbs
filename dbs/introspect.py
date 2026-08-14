from __future__ import annotations

from django.apps import apps
from django.conf import settings
from django.db import models

from .registry import BackupRegistry, FieldType, ModelBackup

DEFAULT_EXCLUDES = {
    "contenttypes.contenttype",
    "auth.permission",
    "admin.logentry",
    "sessions.session",
}


def _label(model) -> str:
    return f"{model._meta.app_label}.{model._meta.model_name}"


def _excluded_labels() -> set[str]:
    excluded = set(DEFAULT_EXCLUDES)
    for label in getattr(settings, "DBS_EXCLUDE_MODELS", None) or ():
        normalized = label.lower()
        if normalized.startswith("-"):
            excluded.discard(normalized[1:])
        else:
            excluded.add(normalized)
    return excluded


def discover_models(registry: BackupRegistry) -> list[type]:
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
    for name, ftype in overrides.items():
        result[name] = ftype
    return result


def file_fields(model, config: ModelBackup) -> dict[str, FieldType]:
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
        if not progressed:
            ordered.extend(remaining)
            break
    return ordered
