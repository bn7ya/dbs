from __future__ import annotations

from rest_framework import status
from rest_framework.exceptions import APIException


class NoAllowedFolders(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "no_allowed_folders"
    default_detail = "This server has no folders its files may be browsed in."


class PathOutsideRoots(APIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_code = "path_outside_roots"
    default_detail = "That path is outside the folders allowed on this server."


class NotAFile(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "not_a_file"
    default_detail = "Only a file can be downloaded."


class CannotDeleteRoot(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "cannot_delete_root"
    default_detail = "An allowed folder itself cannot be deleted."
