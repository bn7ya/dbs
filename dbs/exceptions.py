"""Exception hierarchy for DBS (Django Backup Solution)."""


class DBSError(Exception):
    """Base class for all DBS errors."""


class ConfigurationError(DBSError):
    """Raised when the backup registry / settings are misconfigured."""


class CryptoError(DBSError):
    """Base class for cryptography related failures."""


class InvalidPassphrase(CryptoError):
    """Raised when the supplied passphrase cannot unwrap the data key.

    This is also raised when the wrapped key material has been tampered
    with, because AES-GCM authentication cannot distinguish the two.
    """


class ContainerError(DBSError):
    """Raised when the backup container is structurally invalid."""


class CorruptionError(ContainerError):
    """Raised when corruption is detected and cannot be repaired.

    The ``report`` attribute carries a :class:`dbs.container.blocks.RepairReport`
    describing exactly which blocks failed so the caller can surface a precise
    diagnosis instead of silently restoring bad data.
    """

    def __init__(self, message, report=None):
        super().__init__(message)
        self.report = report


class RestoreError(DBSError):
    """Raised when data could not be loaded back into the database / storage."""
