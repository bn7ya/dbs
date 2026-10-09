from __future__ import annotations

from rest_framework import status
from rest_framework.exceptions import APIException


class HostKeyChanged(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "host_key_changed"
    default_detail = (
        "The server presented a different host key. Review it before connecting."
    )


class SSHAuthFailed(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "ssh_auth_failed"
    default_detail = "The server refused the username, key or password."


class SSHUnreachable(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_code = "ssh_unreachable"
    default_detail = "The server did not answer over SSH."


class RemoteCommandFailed(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_code = "remote_command_failed"
    default_detail = "A command on the server failed."

    def __init__(
        self, detail: str | None = None, code: str | None = None, *, output: str = ""
    ) -> None:
        super().__init__(detail, code)
        self.output: str = output


class BackupInvalid(RemoteCommandFailed):
    default_code = "backup_invalid"
    default_detail = (
        "The server made a backup file that is not a valid django-dbs backup."
    )


class ArchiveFailed(RemoteCommandFailed):
    default_code = "archive_failed"
    default_detail = "The server could not make the archive."


class RestoreFailed(RemoteCommandFailed):
    default_code = "restore_failed"
    default_detail = "The server could not restore the backup."


class DbsTooOld(RemoteCommandFailed):
    default_code = "dbs_too_old"
    default_detail = (
        "The server's django-dbs is too old for this. Upgrade it to 0.2.2 or later."
    )


class RemoteNotFound(APIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_code = "remote_not_found"
    default_detail = "That folder or file is not on the server."


class RemotePermissionDenied(APIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_code = "remote_permission_denied"
    default_detail = "The server does not let this user read that folder or file."


class FileExists(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "file_exists"
    default_detail = "Something with that name is already in this folder on the server."


class FolderNotEmpty(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "folder_not_empty"
    default_detail = "The folder is not empty."


class FileTooLarge(APIException):
    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    default_code = "file_too_large"
    default_detail = "The file on the server is too large to read."


class PassphraseMissing(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "passphrase_missing"
    default_detail = "The manager does not hold this server's backup passphrase."


class NoPrivateKey(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "no_private_key"
    default_detail = "This server signs in with a password, so it has no key."
