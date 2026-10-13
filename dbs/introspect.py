from __future__ import annotations

from functools import reduce
from operator import or_

from django.apps import apps
from django.conf import settings
from django.db import models

from .registry import BackupRegistry, FieldType, ModelBackup

DEFAULT_EXCLUDES = {
    "contenttypes.contenttype",
    "auth.permission",
    "admin.logentry",
    "sessions.session",
    "dbs.backuprecord",
    "dbs.auditevent",
    "dbs.sessionevent",
    "dbs.anomalyevent",
    "dbs.lockout",
    "dbs.lease",
    "dbs.backupschedule",
}


def _label(model) -> str:
    return f"{model._meta.app_label}.{model._meta.model_name}"


def _configured_exclusions() -> list[str]:
    return [label.lower() for label in getattr(settings, "DBS_EXCLUDE_MODELS", None) or ()]


def _excluded_labels() -> set[str]:
    excluded = set(DEFAULT_EXCLUDES)
    for normalized in _configured_exclusions():
        if normalized.startswith("-"):
            excluded.discard(normalized[1:])
        else:
            excluded.add(normalized)
    return excluded


def _reincluded_labels() -> set[str]:
    return {label[1:] for label in _configured_exclusions() if label.startswith("-")}


def unmanaged_models_left_out() -> list[type]:
    reincluded = _reincluded_labels()
    return [
        model
        for model in apps.get_models()
        if not model._meta.managed
        and not model._meta.proxy
        and _label(model) not in reincluded
    ]


def _discovered_models() -> list[type]:
    excluded = _excluded_labels()
    left_out = set(unmanaged_models_left_out())
    return [
        model
        for model in apps.get_models()
        if not model._meta.proxy
        and not model._meta.abstract
        and model not in left_out
        and _label(model) not in excluded
    ]


class ParentRows(ModelBackup):
    def __init__(self):
        super().__init__()
        self.children: list = []

    def get_queryset(self, model):
        selections = [
            models.Q(pk__in=config.get_queryset(child).values(link.attname))
            for child, config, link in self.children
        ]
        return model._base_manager.filter(reduce(or_, selections))


def parent_links(model) -> dict:
    return {
        parent: link
        for parent, link in model._meta.parents.items()
        if link is not None
    }


def backup_plan(registry: BackupRegistry, models: list | None = None) -> list[tuple]:
    if models:
        chosen = list(models)
    elif registry.is_empty():
        chosen = _discovered_models()
    else:
        chosen = registry.models()
    configs = {model: config_for(registry, model) for model in chosen}
    pending = list(chosen)
    while pending:
        child = pending.pop(0)
        for parent, link in parent_links(child).items():
            if parent not in configs:
                configs[parent] = ParentRows()
                pending.append(parent)
            if isinstance(configs[parent], ParentRows):
                configs[parent].children.append((child, configs[child], link))
    return [(model, configs[model]) for model in topological_order(list(configs))]


def discover_models(registry: BackupRegistry) -> list[type]:
    return [model for model, _config in backup_plan(registry)]


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
    ancestors = {
        model: {parent for parent in model._meta.get_parent_list() if parent in model_set}
        for model in model_list
    }
    deps: dict[type, set] = {model: set(ancestors[model]) for model in model_list}
    for model in model_list:
        for field in model._meta.local_fields:
            if (
                field.is_relation
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
            cycle_breaker = next(
                (model for model in remaining if ancestors[model] <= resolved),
                remaining[0],
            )
            ordered.append(cycle_breaker)
            resolved.add(cycle_breaker)
            remaining.remove(cycle_breaker)
    return ordered
