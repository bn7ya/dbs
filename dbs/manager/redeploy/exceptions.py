from __future__ import annotations

from rest_framework import status
from rest_framework.exceptions import APIException


class SameServer(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "same_server"
    default_detail = "Choose a target server other than the source."


class ConfirmNameMismatch(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "confirm_name_mismatch"
    default_detail = "Type the target server's name exactly as it is shown."


class TargetNotReady(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "target_not_ready"
    default_detail = (
        "The target server needs the project's code, a virtual environment and "
        "django-dbs before it can take a redeploy."
    )
