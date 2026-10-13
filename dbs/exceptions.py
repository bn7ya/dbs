class DBSError(Exception):
    pass


class ConfigurationError(DBSError):
    pass


class HostKeyError(ConfigurationError):
    pass


class CryptoError(DBSError):
    pass


class InvalidPassphrase(CryptoError):
    pass


class ContainerError(DBSError):
    pass


class CorruptionError(ContainerError):
    def __init__(self, message, report=None):
        super().__init__(message)
        self.report = report


class RestoreError(DBSError):
    pass


class BackupError(DBSError):
    pass


class MissingSourceFiles(BackupError):
    def __init__(self, message, files):
        super().__init__(message)
        self.files = files
