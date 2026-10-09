from __future__ import annotations

from django.conf import settings
from rest_framework import status
from rest_framework.exceptions import APIException


class InvalidPassword(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "invalid_password"
    default_detail = "That password is not right."


class TooManyAttempts(APIException):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_code = "too_many_attempts"
    default_detail = "Too many attempts. Wait a few minutes and try again."

    def __init__(self) -> None:
        super().__init__()
        self.wait = settings.AUTH_FAILURE_WINDOW


class SetupDone(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "setup_done"
    default_detail = "The first account already exists. Sign in instead."


class SetupTokenInvalid(APIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_code = "setup_token_invalid"
    default_detail = "Open the setup link that django_dbs run printed."


class PasswordInvalid(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "password_invalid"
    default_detail = "Choose a stronger password."
