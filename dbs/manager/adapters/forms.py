from __future__ import annotations

from typing import Any

from rest_framework import serializers


def validated(
    serializer: type[serializers.Serializer],
    data: dict[str, Any],
    partial: bool = False,
) -> dict[str, Any]:
    form = serializer(data=data, partial=partial)
    form.is_valid(raise_exception=True)
    return dict(form.validated_data)
