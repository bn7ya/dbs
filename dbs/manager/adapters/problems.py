from __future__ import annotations

from typing import Any

from rest_framework.exceptions import APIException


def problem(exc: APIException) -> str:
    return _flatten(exc.detail)


def _flatten(detail: Any, field: str = "") -> str:
    if isinstance(detail, dict):
        return "; ".join(
            _flatten(value, key if key != "non_field_errors" else "")
            for key, value in detail.items()
        )
    if isinstance(detail, list):
        return "; ".join(_flatten(item, field) for item in detail)
    message = str(detail)
    return f"{field.replace('_', ' ')}: {message}" if field else message
