from __future__ import annotations

from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail

from dbs.manager.common.paths import absolute_path

PATH_MAX = 4096
ENTRY_KINDS = ["file", "folder", "link", "other"]
ABSOLUTE_PATH_REQUIRED = (
    "Use an absolute path that starts with / and has no '..' in it."
)


def _absolute(value: str) -> str:
    if not value:
        return value
    path = absolute_path(value)
    if path is None:
        raise serializers.ValidationError(
            ErrorDetail(ABSOLUTE_PATH_REQUIRED, code="absolute_path_required")
        )
    return path


def _optional_path() -> serializers.CharField:
    return serializers.CharField(
        max_length=PATH_MAX, trim_whitespace=False, required=False, allow_blank=True
    )


class BrowseQuerySerializer(serializers.Serializer):
    path = _optional_path()

    def validate_path(self, value: str) -> str:
        return _absolute(value)


class DiscoverRequestSerializer(serializers.Serializer):
    project_dir = _optional_path()
    account_password = serializers.CharField(
        max_length=128,
        trim_whitespace=False,
        required=False,
        allow_blank=True,
        write_only=True,
    )

    def validate_project_dir(self, value: str) -> str:
        return _absolute(value)


class BrowseEntrySerializer(serializers.Serializer):
    name = serializers.CharField(read_only=True)
    path = serializers.CharField(read_only=True)
    kind = serializers.ChoiceField(choices=ENTRY_KINDS, read_only=True)
    size = serializers.IntegerField(read_only=True, allow_null=True)
    modified = serializers.DateTimeField(
        source="mtime", read_only=True, allow_null=True
    )


class BrowseListingSerializer(serializers.Serializer):
    path = serializers.CharField(read_only=True)
    parent = serializers.CharField(read_only=True, allow_null=True)
    home = serializers.CharField(read_only=True)
    project = serializers.BooleanField(read_only=True)
    truncated = serializers.BooleanField(read_only=True)
    count = serializers.IntegerField(read_only=True)
    next = serializers.URLField(read_only=True, allow_null=True)
    previous = serializers.URLField(read_only=True, allow_null=True)
    results = BrowseEntrySerializer(many=True, read_only=True)
