from .registry import BackupRegistry, FieldType, ModelBackup, backup_registry

__version__ = "0.2.1"

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
    if name in {"create_backup", "restore_backup", "validate_backup"}:
        from . import engine

        return getattr(engine, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
