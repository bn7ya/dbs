from .keys import default_passphrase
from .registry import BackupRegistry, FieldType, ModelBackup, backup_registry

__version__ = "0.8.0"

__all__ = [
    "backup_registry",
    "BackupRegistry",
    "FieldType",
    "ModelBackup",
    "default_passphrase",
    "create_backup",
    "write_backup",
    "BackupSummary",
    "restore_backup",
    "validate_backup",
    "__version__",
]

_ENGINE = {"create_backup", "write_backup", "BackupSummary", "restore_backup", "validate_backup"}


def __getattr__(name):
    if name in _ENGINE:
        from . import engine

        return getattr(engine, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
