import importlib

__all__ = [
    "BackupSummary",
    "create_backup",
    "write_backup",
    "restore_backup",
    "validate_backup",
    "ValidationResult",
]

_SOURCES = {
    "BackupSummary": "backup",
    "create_backup": "backup",
    "write_backup": "backup",
    "restore_backup": "restore",
    "validate_backup": "validate",
    "ValidationResult": "validate",
}


def __getattr__(name):
    module_name = _SOURCES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(f".{module_name}", __name__), name)
