from __future__ import annotations

from datetime import datetime

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
        self,
        detail: str | None = None,
        code: str | None = None,
        *,
        output: str = "",
        settles_at: datetime | None = None,
    ) -> None:
        super().__init__(detail, code)
        self.output: str = output
        self.settles_at: datetime | None = settles_at


class RemoteCommandTimedOut(RemoteCommandFailed):
    status_code = status.HTTP_504_GATEWAY_TIMEOUT
    default_code = "remote_command_timed_out"
    default_detail = "A command on the server ran out of time and was stopped."


class ServerConnectionLost(RemoteCommandFailed):
    default_code = "connection_lost"
    default_detail = "The connection to the server was lost while it worked."


class StreamBroken(RemoteCommandFailed):
    default_code = "stream_broken"
    default_detail = (
        "The connection broke while the backup was arriving. The server keeps it, "
        "and the manager collects it at the next connection."
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


class HostKeyConfirmationMissing(APIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_code = "host_key_confirmation_missing"
    default_detail = (
        "There is no such host key confirmation, or its 10 minutes are over. "
        "Read the host key again."
    )


class HostKeyConfirmationMismatch(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "host_key_confirmation_mismatch"
    default_detail = "This host key confirmation is for another address or port."


class HostKeyNotConfirmed(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "host_key_not_confirmed"
    default_detail = (
        "Nobody has confirmed this host key yet. A person confirms it in the "
        "manager's Servers page or with django_dbs server confirm-host-key."
    )


class HostKeyRejected(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "host_key_rejected"
    default_detail = "A person rejected this host key, so it cannot be pinned."


class HostKeyDecided(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "host_key_decided"
    default_detail = "This host key was already confirmed or rejected."
