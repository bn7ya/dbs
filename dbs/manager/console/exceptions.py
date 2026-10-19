from __future__ import annotations

from rest_framework import status
from rest_framework.exceptions import APIException


class ConsoleBusy(APIException):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_code = "console_busy"
    default_detail = "Your previous command is still running; wait for it to finish."


class PasswordNeeded(Exception):
    pass


class ConsoleStopped(Exception):
    def __init__(self, status: int, message: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.message = message
