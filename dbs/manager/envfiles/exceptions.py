from __future__ import annotations

from rest_framework import status
from rest_framework.exceptions import APIException


class EnvPathMissing(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "env_path_missing"
    default_detail = "This server has no .env path set."


class EnvTooLarge(APIException):
    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    default_code = "env_too_large"
    default_detail = "The .env file on the server is too large to keep."


class DifferentServers(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "different_servers"
    default_detail = "Only two versions of the same server's .env can be compared."
