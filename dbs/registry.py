"""The developer-facing backup registry.

A project opts models into the backup the same way it opts them into the admin:
either let DBS auto-discover everything, or register a model with a small
:class:`ModelBackup` subclass that declares per-field overrides.

    from dbs import backup_registry, FieldType, ModelBackup

    @backup_registry.register(Invoice)
    class InvoiceBackup(ModelBackup):
        overrides = {
            "scanned_pdf_path": FieldType.FILE_PATH,  # CharField holding a path
            "render_cache": FieldType.EXCLUDE,
        }
        file_roots = [settings.MEDIA_ROOT]
"""

from __future__ import annotations

import enum


class FieldType(enum.Enum):
    """How a model field should be treated by the backup engine."""

    VALUE = "value"          # plain column value (default for everything)
    FILE = "file"            # FileField/ImageField -> embed the file's bytes
    FILE_PATH = "file_path"  # a string column holding a path -> embed that file
    EXCLUDE = "exclude"      # drop this field from the backup entirely


class ModelBackup:
    """Base class for per-model backup configuration.

    Everything is auto-detected by default; subclass only to declare exceptions.
    """

    #: Map of ``field_name -> FieldType`` overriding the auto-detected type.
    overrides: dict[str, FieldType] = {}

    #: Extra directories (outside any model) whose files should be embedded.
    file_roots: list[str] = []

    def get_queryset(self, model):
        """Return the queryset to back up (override to filter/scope)."""
        return model._default_manager.all()


class BackupRegistry:
    """Holds the set of models (and their config) to include in a backup."""

    def __init__(self) -> None:
        self._configs: dict[type, ModelBackup] = {}

    def register(self, model):
        """Register ``model`` and return a decorator for an optional config.

        Works both as a bare call and as a decorator::

            backup_registry.register(MyModel)                 # default config

            @backup_registry.register(MyModel)                # custom config
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


#: The process-wide registry, mirroring ``django.contrib.admin.site``.
backup_registry = BackupRegistry()
