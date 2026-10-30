from __future__ import annotations

from rest_framework import status
from rest_framework.exceptions import APIException

from dbs.manager.servers.exceptions import RemoteCommandFailed


class SameServer(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "same_server"
    default_detail = "Choose a server other than the one the applications run on."


class NothingToMove(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "nothing_to_move"
    default_detail = "The server has no application to move."


class MoveBlocked(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "move_blocked"
    default_detail = "The plan found something that stops the move; it lists what."


class ServerMoveRunning(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "server_move_running"
    default_detail = "A move already runs on one of these servers."


class MoveNotResumable(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "move_not_resumable"
    default_detail = (
        "Only a move for real between the same servers that stopped can be resumed."
    )


class SudoMissing(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "sudo_missing"
    default_detail = (
        "The server has no sudo, so the move cannot install what the applications need."
    )


class SudoPasswordRequired(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "sudo_password_required"
    default_detail = "Enter the sudo password of the SSH user on this server."


class SudoPasswordWrong(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "sudo_password_wrong"
    default_detail = "sudo refused the password."


class SudoNeedsTty(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "sudo_needs_tty"
    default_detail = (
        "sudo on this server asks for a terminal (requiretty); allow the SSH user "
        "without one."
    )


class PrivilegedCommandFailed(RemoteCommandFailed):
    default_code = "privileged_command_failed"
    default_detail = "A command run as root on the server failed."


class PackageInstallFailed(RemoteCommandFailed):
    default_code = "package_install_failed"
    default_detail = "The packages could not be installed."


class RepositoryKeyMismatch(RemoteCommandFailed):
    default_code = "repository_key_mismatch"
    default_detail = "The repository's signing key is not the one the manager expects."


class TransferDigestMismatch(RemoteCommandFailed):
    default_code = "transfer_digest_mismatch"
    default_detail = "What arrived on the new server differs from what was sent."


class TargetFolderNotEmpty(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "target_folder_not_empty"
    default_detail = "Something is already in the folder on the new server."


class TargetFileExists(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "file_exists_on_target"
    default_detail = "A file the move would write is already on the new server."


class DatabaseExists(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "database_exists_on_target"
    default_detail = "The database is already on the new server; the move leaves it alone."


class DatabaseCredentialsUnknown(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "database_credentials_unknown"
    default_detail = "The moved application did not say which database it uses."


class MovedApplicationNotFound(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "moved_application_not_found"
    default_detail = "Discovery did not find the moved application on the new server."


class ImageMismatch(RemoteCommandFailed):
    default_code = "image_mismatch"
    default_detail = "The image loaded on the new server is not the one that was sent."
