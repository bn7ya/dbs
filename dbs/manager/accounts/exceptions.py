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

    def __init__(self, wait: int | None = None) -> None:
        super().__init__()
        self.wait = settings.AUTH_FAILURE_WINDOW if wait is None else wait


class SetupDone(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "setup_done"
    default_detail = "The first account already exists. Sign in instead."


class SetupTokenInvalid(APIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_code = "setup_token_invalid"
    default_detail = "Open the setup link that django_dbs run printed."


class InvalidCode(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "invalid_code"
    default_detail = "That code is not right, or it was already used."


class SignInExpired(APIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_code = "sign_in_expired"
    default_detail = "The sign-in took too long or was not started. Sign in again."


class TwoFactorEnrolled(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "two_factor_enrolled"
    default_detail = "This account already has two-factor sign-in. Enter its code."


class TwoFactorMissing(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "two_factor_missing"
    default_detail = "This account has no two-factor sign-in yet. Set it up first."


class PasswordChangeRequired(APIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_code = "password_change_required"
    default_detail = "Your password has expired. Change it to continue, or sign out."


class MasterProtected(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "master_protected"
    default_detail = (
        "The master account cannot be demoted, disabled or deleted. Hand the master "
        "role to another account first."
    )


class OwnAccount(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "own_account"
    default_detail = "Ask the master account to change this for your own account."


class AccountInactive(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "account_inactive"
    default_detail = "That account is disabled. Enable it first."


class AccountNotFound(APIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_code = "not_found"
    default_detail = "There is no such account."
