from __future__ import annotations

from rest_framework import status
from rest_framework.exceptions import APIException


class SameApplication(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "same_application"
    default_detail = "Choose a target application other than the source."


class ConfirmNameMismatch(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "confirm_name_mismatch"
    default_detail = "Type the target application's name exactly as it is shown."


class TargetNotReady(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "target_not_ready"
    default_detail = (
        "The target application needs the project's code, its Python and "
        "django-dbs before it can take a redeploy."
    )


class SourceUnreachable(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "source_unreachable"
    default_detail = (
        "The old application cannot be reached and no backup of it was chosen "
        "to restore."
    )


class NoBackupToRehearse(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "no_backup_to_rehearse"
    default_detail = (
        "The manager holds no backup of the old application for the rehearsal "
        "to restore. "
        "Take one first, or choose one."
    )


class NotRevertable(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "move_not_revertable"
    default_detail = (
        "Only a move for real that stopped after it changed the new application, with "
        "its .env or data recorded first, can be reverted."
    )
