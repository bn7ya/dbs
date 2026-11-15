from __future__ import annotations

from rest_framework import status
from rest_framework.exceptions import APIException


class UpdateBusy(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "update_busy"
    default_detail = (
        "A job is running or a terminal is open. The update restarts the manager, so "
        "wait until they are done."
    )


class UpdateFromTerminal(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "update_from_terminal"
    default_detail = (
        "This manager cannot restart itself here. Stop it and run django_dbs update in "
        "a terminal on its computer."
    )


class UpdateRefused(APIException):
    status_code = status.HTTP_409_CONFLICT

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message, code)
        self.default_code = code
