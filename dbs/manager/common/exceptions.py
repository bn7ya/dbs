from __future__ import annotations

import logging
from typing import Any, cast

from django.core.exceptions import PermissionDenied
from django.http import Http404
from rest_framework import exceptions
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger: logging.Logger = logging.getLogger(__name__)

GENERIC_MESSAGE: str = "Something went wrong. Try again."
UNEXPECTED: str = "unexpected"


def _flatten(detail: object) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list) and detail:
        return _flatten(detail[0])
    if isinstance(detail, dict) and detail:
        return _flatten(next(iter(detail.values())))
    return GENERIC_MESSAGE


def _codes(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [code for item in value.values() for code in _codes(item)]
    if isinstance(value, list):
        return [code for item in value for code in _codes(item)]
    return []


def error_code_of(exc: BaseException) -> str:
    if isinstance(exc, exceptions.ValidationError) and (
        named := _codes(exc.get_codes())
    ):
        return named[0]
    if isinstance(exc, exceptions.APIException):
        return exc.default_code
    if isinstance(exc, Http404):
        return exceptions.NotFound.default_code
    if isinstance(exc, PermissionDenied):
        return exceptions.PermissionDenied.default_code
    return UNEXPECTED


def _field_codes(exc: Exception) -> dict[str, list[str]] | None:
    if isinstance(exc, exceptions.ValidationError) and isinstance(
        codes := exc.get_codes(), dict
    ):
        return {name: _codes(value) for name, value in codes.items()}
    return None


def exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    response: Response | None = drf_exception_handler(exc, context)

    if response is None:
        if not isinstance(exc, (Http404, PermissionDenied)):
            logger.exception("Unhandled exception in %s", context.get("view"))
        return None

    fields: dict[str, list[str]] | None = _field_codes(exc)
    response.data = {
        "error": {
            "code": cast(exceptions.ValidationError, exc).default_code
            if fields
            else error_code_of(exc),
            "message": _flatten(response.data),
            **({"fields": fields} if fields else {}),
        }
    }
    return response
