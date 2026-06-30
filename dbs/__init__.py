"""DBS -- Django Backup Solution.

A redundant, self-healing, encrypted, single-file backup for Django projects.

Public API::

    from dbs import backup_registry, FieldType, ModelBackup
    from dbs import create_backup, restore_backup, validate_backup
"""

from .registry import BackupRegistry, FieldType, ModelBackup, backup_registry

__version__ = "0.1.0"

__all__ = [
    "backup_registry",
    "BackupRegistry",
    "FieldType",
    "ModelBackup",
    "create_backup",
    "restore_backup",
    "validate_backup",
    "__version__",
]


def __getattr__(name):
    # Lazily expose the engine entry points so importing ``dbs`` never forces the
    # Django app registry to be ready (the registry/FieldType imports above don't).
    if name in {"create_backup", "restore_backup", "validate_backup"}:
        from . import engine

        return getattr(engine, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
