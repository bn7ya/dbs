from __future__ import annotations

import enum


class FieldType(enum.Enum):
    """How a model field should be treated by the backup engine."""

    VALUE = "value"
    FILE = "file"
    FILE_PATH = "file_path"
    EXCLUDE = "exclude"


class ModelBackup:
    """Base class for per-model backup configuration.

    Everything is auto-detected by default; subclass only to declare exceptions.
    """

    overrides: dict[str, FieldType] = {}

    file_roots: list[str] = []

    def get_queryset(self, model):
        """Return the queryset to back up (override to filter/scope).

        Reads through ``model._base_manager`` so every row is included. A
        project's default manager may hide rows (a soft-delete manager that
        filters out ``is_deleted=True``, a tenant-scoped manager); backing up
        through it would drop those rows, and a restore would then fail its
        constraint check wherever a visible row still points at a hidden one.
        Restore and flush already use ``_base_manager``, so backup now matches.
        """
        return model._base_manager.all()


class BackupRegistry:
    """Holds the set of models (and their config) to include in a backup."""

    def __init__(self) -> None:
        self._configs: dict[type, ModelBackup] = {}

    def register(self, model):
        """Register ``model`` and return a decorator for an optional config.

        Works both as a bare call and as a decorator::

            backup_registry.register(MyModel)

            @backup_registry.register(MyModel)
            class MyModelBackup(ModelBackup):
                ...
        """
        self._configs.setdefault(model, ModelBackup())

        def _decorator(config_cls):
            self._configs[model] = config_cls()
            return config_cls

        return _decorator

    def unregister(self, model) -> None:
        self._configs.pop(model, None)

    def clear(self) -> None:
        self._configs.clear()

    def is_empty(self) -> bool:
        return not self._configs

    def get(self, model) -> ModelBackup | None:
        return self._configs.get(model)

    def items(self):
        return list(self._configs.items())

    def models(self):
        return list(self._configs.keys())


backup_registry = BackupRegistry()
