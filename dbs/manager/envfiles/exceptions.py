from __future__ import annotations

from rest_framework import status
from rest_framework.exceptions import APIException


class EnvPathMissing(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "env_path_missing"
    default_detail = "This application has no .env path set."


class EnvTooLarge(APIException):
    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    default_code = "env_too_large"
    default_detail = "The application's .env file is too large to keep."


class EnvFolderShared(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "env_folder_shared"
    default_detail = (
        "Another account can write to the folder this .env is in, or the one it "
        "points into, so the manager neither reads nor replaces it."
    )


class DifferentApplications(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "different_applications"
    default_detail = (
        "Only two versions of the same application's .env can be compared."
    )
